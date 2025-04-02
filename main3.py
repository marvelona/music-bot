import os
import requests
import tempfile
import asyncio
import logging
import functools
import threading
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from dotenv import load_dotenv
import deezer
import yt_dlp

# Load environment variables
load_dotenv()

# Ensure environment variables are set
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TARGET_GROUP_CHAT_ID = os.getenv('TARGET_GROUP_CHAT_ID')
if not (TELEGRAM_BOT_TOKEN and TARGET_GROUP_CHAT_ID):
    raise EnvironmentError("Environment variables TELEGRAM_BOT_TOKEN or TARGET_GROUP_CHAT_ID are not set.")

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global cache for song data per chat
group_song_data = {}

# Cache directory for downloaded audio files
CACHE_DIR = "/tmp/music-bot-cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def retry(max_retries=3, delay=2):
    def decorator_retry(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    logger.warning(f"Retry {retries}/{max_retries}. Error: {e}")
                    asyncio.sleep(delay)
            raise e
        return wrapper
    return decorator_retry

# Fetch song details using Deezer for metadata and yt-dlp for audio extraction
@retry()
def fetch_song(query):
    # Initialize Deezer client
    client = deezer.Client()

    try:
        # Search for the song on Deezer
        search_results = client.search(query)
        if not search_results:
            logger.warning(f"No results found for query: {query}")
            return None

        # Manually limit to 3 results
        search_results = list(search_results)[:3]

        songs = []
        for track in search_results:
            song_name = track.title
            artist_name = track.artist.name

            # Search YouTube for the full song to get a downloadable link
            youtube_query = f"{song_name} {artist_name} audio"
            youtube_url = None

            # Use yt-dlp to search YouTube and get the audio URL
            ydl_opts = {
                'format': 'bestaudio/best',  # Keep best quality (e.g., 320kbps if available)
                'extract_audio': True,
                'audio_format': 'mp3',
                'quiet': True,
                'default_search': 'ytsearch',  # Automatically search YouTube
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(youtube_query, download=False)
                    if 'entries' in info and info['entries']:
                        youtube_url = info['entries'][0]['url']  # Direct audio stream URL
                    else:
                        logger.warning(f"No YouTube results for: {youtube_query}")
                        continue
                except Exception as e:
                    logger.error(f"Failed to fetch YouTube audio for {youtube_query}: {e}")
                    continue

            if youtube_url:
                songs.append({
                    "song_name": song_name,
                    "artist_name": artist_name,
                    "download_link": youtube_url
                })
            else:
                logger.warning(f"No downloadable audio found for {song_name} by {artist_name}")
                continue

        if songs:
            return songs
        else:
            logger.warning(f"No downloadable songs found for query: {query}")
            return None

    except Exception as e:
        logger.error(f"Failed to fetch from Deezer: {e}")
        return None

# Command handler for /search (restricted to specific group)
async def search_command(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    if chat_id != int(TARGET_GROUP_CHAT_ID):
        await update.message.reply_text("❌ This bot can only be used in the specific group.")
        return

    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("🛑 Please provide a song name, e.g., `/search Believer`", parse_mode="Markdown")
        return

    await update.message.reply_text("🔍 Searching for songs...")
    song_data = fetch_song(query)

    if song_data:
        group_song_data[chat_id] = song_data
        keyboard = [
            [InlineKeyboardButton(f"🔊 {song['song_name']} - {song['artist_name']}", callback_data=f"{chat_id}_download_{i}")]
            for i, song in enumerate(song_data)
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🎶 Select a song to download:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("❌ No results found.")

# Callback handler for download (restricted to specific group)
@retry()
async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    # Parse callback data
    data = query.data.split('_')
    if len(data) != 3 or data[1] != 'download':
        return  # Silently drop the request if the callback data is invalid

    chat_id, index = int(data[0]), int(data[2])

    if chat_id != int(TARGET_GROUP_CHAT_ID):
        return  # Silently drop the request if not from the target group

    if chat_id not in group_song_data or index >= len(group_song_data[chat_id]):
        return  # Silently drop the request if song data is invalid

    song = group_song_data[chat_id][index]
    download_link = song['download_link']

    # Generate a unique cache file name based on song name and chat ID
    cache_file_name = f"{song['song_name']}_{song['artist_name']}_{chat_id}_{index}.mp3".replace('/', '_').replace(' ', '_')
    temp_file_path = os.path.join(CACHE_DIR, cache_file_name)

    # Check if the file is already cached
    if os.path.exists(temp_file_path):
        logger.info(f"Using cached file: {temp_file_path}")
    else:
        def download_file(download_link, temp_file_path, result):
            start_time = time.time()
            try:
                ydl_opts = {
                    'format': 'bestaudio/best',  # Keep best quality (e.g., 320kbps if available)
                    'extract_audio': True,
                    'audio_format': 'mp3',
                    'outtmpl': temp_file_path,
                    'quiet': True,
                    'no_post_overwrites': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([download_link])
                end_time = time.time()
                logger.info(f"Download completed in {end_time - start_time:.2f} seconds for {download_link}")
                result.append(temp_file_path)
            except Exception as e:
                logger.error(f"Download error for {download_link}: {e}")
                result.append(None)

        result = []
        thread = threading.Thread(target=download_file, args=(download_link, temp_file_path, result))
        thread.start()
        thread.join(timeout=180)

        if not result or not result[0]:
            await query.message.reply_text("❌ Failed to download the song. Please try again.")
            return

    if os.path.exists(temp_file_path):
        with open(temp_file_path, 'rb') as audio_file:
            await query.message.reply_audio(
                audio=audio_file,
                caption=f"🎶 {song['song_name']} - {song['artist_name']}\nPowered by ASI Music"
            )
    else:
        await query.message.reply_text("❌ Failed to download the song. Please try again.")

# Command handler for /help (restricted to specific group)
async def help_command(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    if chat_id != int(TARGET_GROUP_CHAT_ID):
        await update.message.reply_text("❌ This bot can only be used in the specific group.")
        return

    help_text = (
        "🤖 *ASI Music Bot Commands:*\n\n"
        "🎵 `/search <song>` - Search and download songs.\n"
        "ℹ️ Contact @marvelona2 for support.\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# Main function with graceful shutdown
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler('search', search_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    try:
        application.run_polling()
    except KeyboardInterrupt:
        logger.info("Stopping the bot...")
    finally:
        application.stop()

if __name__ == '__main__':
    main()
