import os
import asyncio
import logging
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
import deezer
import yt_dlp

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TARGET_GROUP_CHAT_ID = os.getenv('TARGET_GROUP_CHAT_ID')
if not (TELEGRAM_BOT_TOKEN and TARGET_GROUP_CHAT_ID):
    raise EnvironmentError("Environment variables TELEGRAM_BOT_TOKEN or TARGET_GROUP_CHAT_ID are not set.")

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global cache for song data per chat
group_song_data = {}

# Cache directory using tempfile for cross-platform compatibility
CACHE_DIR = os.path.join(tempfile.gettempdir(), "music-bot-cache")
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# Retry decorator with async sleep
def retry(max_retries=3, delay=2):
    def decorator_retry(func):
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Retry {attempt + 1}/{max_retries}. Error: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All retries failed for {func.__name__}: {e}")
                        return None
        return wrapper
    return decorator_retry

# Fetch song details using Deezer and yt-dlp
@retry()
async def fetch_song(query):
    client = deezer.Client()
    try:
        search_results = client.search(query)[:3]  # Limit to 3 results
        if not search_results:
            logger.warning(f"No results found for query: {query}")
            return None

        songs = []
        for track in search_results:
            song_name = track.title
            artist_name = track.artist.name
            youtube_query = f"{song_name} {artist_name} audio"

            ydl_opts = {
                'format': 'bestaudio/best',
                'extract_audio': True,
                'audio_format': 'mp3',
                'quiet': True,
                'default_search': 'ytsearch',
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, youtube_query, download=False)
                if 'entries' in info and info['entries']:
                    youtube_url = info['entries'][0]['url']
                    songs.append({
                        "song_name": song_name,
                        "artist_name": artist_name,
                        "download_link": youtube_url
                    })
                else:
                    logger.warning(f"No YouTube results for: {youtube_query}")
                    continue

        return songs if songs else None
    except Exception as e:
        logger.error(f"Failed to fetch from Deezer: {e}")
        return None

# Command handler for /search
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id != int(TARGET_GROUP_CHAT_ID):
        await update.message.reply_text("❌ This bot can only be used in the specific group.")
        return

    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("🛑 Please provide a song name, e.g., `/search Believer`", parse_mode="Markdown")
        return

    await update.message.reply_text("🔍 Searching for songs...")
    song_data = await fetch_song(query)

    if song_data:
        group_song_data[chat_id] = song_data
        keyboard = [
            [InlineKeyboardButton(f"🔊 {song['song_name']} - {song['artist_name']}", callback_data=f"{chat_id}_download_{i}")]
            for i, song in enumerate(song_data)
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🎶 Select a song to download:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("❌ No results found.")

# Async download function
async def download_audio(download_link, temp_file_path):
    ydl_opts = {
        'format': 'bestaudio/best',
        'extract_audio': True,
        'audio_format': 'mp3',
        'outtmpl': temp_file_path,
        'quiet': True,
        'no_post_overwrites': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            await asyncio.to_thread(ydl.download, [download_link])
            if os.path.exists(temp_file_path) and os.path.getsize(temp_file_path) <= 50 * 1024 * 1024:  # 50 MB limit
                return temp_file_path
            logger.warning(f"File {temp_file_path} exceeds 50 MB or failed to download")
            return None
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None

# Callback handler for download
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    if len(data) != 3 or data[1] != 'download':
        return

    chat_id, index = int(data[0]), int(data[2])
    if chat_id != int(TARGET_GROUP_CHAT_ID) or chat_id not in group_song_data or index >= len(group_song_data[chat_id]):
        return

    song = group_song_data[chat_id][index]
    download_link = song['download_link']

    cache_file_name = f"{song['song_name']}_{song['artist_name']}_{chat_id}_{index}.mp3".replace('/', '_').replace(' ', '_')
    temp_file_path = os.path.join(CACHE_DIR, cache_file_name)

    downloading_msg = await query.message.reply_text(f"⬇️ Downloading {song['song_name']}...")
    if os.path.exists(temp_file_path):
        logger.info(f"Using cached file: {temp_file_path}")
    else:
        temp_file_path = await download_audio(download_link, temp_file_path)
        if not temp_file_path:
            await downloading_msg.edit_text("❌ Failed to download the song. Please try again.")
            return

    await downloading_msg.edit_text(f"⬆️ Uploading {song['song_name']}...")
    with open(temp_file_path, 'rb') as audio_file:
        await query.message.reply_audio(
            audio=audio_file,
            caption=f"🎶 {song['song_name']} - {song['artist_name']}\nPowered by ASI Music"
        )
    await downloading_msg.delete()
    logger.info(f"Sent audio to chat {chat_id}")

# Command handler for /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler('search', search_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    try:
        application.run_polling()
    except KeyboardInterrupt:
        logger.info("Stopping the bot...")

if __name__ == '__main__':
    main()
