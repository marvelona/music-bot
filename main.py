import os
import requests
import tempfile
import asyncio
import logging
import functools
import mimetypes
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Ensure environment variables are set
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TARGET_GROUP_CHAT_ID = os.getenv('TARGET_GROUP_CHAT_ID')
if not (TELEGRAM_BOT_TOKEN and TARGET_GROUP_CHAT_ID):
    raise EnvironmentError("Environment variables TELEGRAM_BOT_TOKEN or TARGET_GROUP_CHAT_ID are not set.")

# APIs
SPOTIFY_API = "https://spotifyapi.nepdevsnepcoder.workers.dev/?songname={query}"
JIOSAAVN_API = "https://jiosaavn-api-codyandersan.vercel.app/search/all?query={query}&page=1&limit=6"

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global cache for song data per chat
group_song_data = {}

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

# Fetch song details from APIs with retry mechanism
@retry()
def fetch_song(query):
    query = query.replace(' ', '+')

    # Try Spotify API first
    for api in [SPOTIFY_API, JIOSAAVN_API]:
        try:
            response = requests.get(api.format(query=query), timeout=(5, 10))
            response.raise_for_status()
            data = response.json()
            if data:
                if api == SPOTIFY_API:
                    return data
                elif 'results' in data and data['results']:
                    return [
                        {"song_name": result['title'], "artist_name": result['primary_artists'], "download_link": result['perma_url']}
                        for result in data['results']
                    ]
        except requests.RequestException as e:
            logger.error(f"Failed to fetch from {api}: {e}")

    return None

# Command handler for /search (restricted to specific group)
async def search_command(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    # Check if the command is being issued in the specified group
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
        group_song_data[chat_id] = song_data[:3]
        keyboard = [
            [InlineKeyboardButton(f"🔊 {song['song_name']} - {song['artist_name']}", callback_data=f"{chat_id}_download_{i}")]
            for i, song in enumerate(song_data[:3])
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
        await query.message.reply_text("❌ Invalid callback data.")
        return

    chat_id = int(data[0])
    index = int(data[2])

    # Check if the callback is from the allowed group
    if chat_id != int(TARGET_GROUP_CHAT_ID):
        await query.message.reply_text("❌ This action can only be performed in the specific group.")
        return

    # Validate group song data
    if chat_id not in group_song_data or index >= len(group_song_data[chat_id]):
        await query.message.reply_text("❌ Song data not found. Please search again.")
        return

    song = group_song_data[chat_id][index]
    download_link = song['download_link']

    try:
        response = requests.get(download_link, stream=True, timeout=(5, 15))
        response.raise_for_status()
        
        file_ext = mimetypes.guess_extension(response.headers.get('content-type', '').split(';')[0]).split('.')[-1] or 'mp3'
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as temp_file:
            for chunk in response.iter_content(chunk_size=8192): 
                temp_file.write(chunk)
            temp_file_path = temp_file.name

        with open(temp_file_path, 'rb') as audio_file:
            await query.message.reply_audio(
                audio=audio_file,
                caption=f"🎶 {song['song_name']} - {song['artist_name']}\nPowered by ASI Music"
            )
        os.remove(temp_file_path)
    except requests.RequestException as e:
        logger.error(f"Download error: {e}")
        await query.message.reply_text("❌ Failed to download the song. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error during download: {e}")
        await query.message.reply_text("❌ An error occurred while processing your request.")

# Command handler for /help (restricted to specific group)
async def help_command(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    # Check if the command is being issued in the specified group
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
