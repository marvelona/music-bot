import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from dotenv import load_dotenv
import tempfile
import time

# Load environment variables
load_dotenv()

# Telegram bot token and allowed group ID from environment variable
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALLOWED_CHAT_ID = int(os.getenv('ALLOWED_CHAT_ID', '-1002363559013'))

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# Global dictionary to store song data for each user
user_song_data = {}

# Function to fetch song details from the Spotify API with retry mechanism
def get_spotify_song(song_name):
    query = song_name.replace(' ', '+')
    api_url = f"https://spotifyapi.nepdevsnepcoder.workers.dev/?songname={query}"
    retries = 0

    while retries < MAX_RETRIES:
        try:
            response = requests.get(api_url)
            if response.status_code == 200:
                data = response.json()
                return data if data else None
            else:
                retries += 1
                time.sleep(RETRY_DELAY)
        except Exception as e:
            print(f"Error fetching song details: {e}")
            retries += 1
            time.sleep(RETRY_DELAY)

    return None

# Command handler for /song command with loading message and retry mechanism
async def song_command(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        await update.message.reply_text("This bot is restricted to a specific group.")
        return

    if context.args:
        query = ' '.join(context.args)
        loading_message = await update.message.reply_text("🔍 Searching for song, please wait...")

        song_data = get_spotify_song(query)

        if song_data:
            song = song_data[0]
            song_name = song['song_name']
            artist_name = song['artist_name']

            # Inline buttons for download, cancel, and search more results
            keyboard = [
                [InlineKeyboardButton("⬇️ Download", callback_data="download_0")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
                [InlineKeyboardButton("🔄 Search more results", callback_data="search_more")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"🎶 Found: *{song_name}* by *{artist_name}*\nClick below to download.",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )

            # Cache song data globally for the user
            user_song_data[update.effective_user.id] = song_data
        else:
            await update.message.reply_text("❌ No results found for your query.")
        
        await context.bot.delete_message(chat_id=loading_message.chat_id, message_id=loading_message.message_id)
    else:
        await update.message.reply_text("🛑 Please provide a song name to search, e.g., /song Believer")

# Handler for song download with improved file management
async def download_song(update: Update, context: CallbackContext, index: int) -> None:
    user_id = update.effective_user.id
    song_data = user_song_data.get(user_id)

    if not song_data:
        await update.callback_query.message.reply_text("❌ No song data found.")
        return

    if index >= len(song_data):
        await update.callback_query.message.reply_text("❌ Invalid song index.")
        return

    song = song_data[index]
    download_link = song['download_link']
    song_name = song['song_name']

    try:
        response = requests.get(download_link, stream=True, timeout=10)
        if response.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                temp_file.write(response.content)
                temp_file_path = temp_file.name

            await update.callback_query.message.reply_audio(
                audio=open(temp_file_path, 'rb'),
                title=song_name
            )

            # Clean up the temporary file after sending
            os.remove(temp_file_path)
            await update.callback_query.answer("Song downloaded successfully.")
        else:
            await update.callback_query.message.reply_text("❌ Failed to download the song.")
    except Exception as e:
        print(f"Error downloading the song: {e}")
        await update.callback_query.message.reply_text("❌ An error occurred while downloading the song.")
    finally:
        # Ensure file is removed even if error occurs
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

# Callback handler to handle inline button presses
async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.message.edit_text("✅ Request canceled.")
    elif query.data == "search_more":
        await query.message.reply_text("Please use /search to find more results.")
    elif query.data.startswith("download_"):
        index = int(query.data.split('_')[1])
        await download_song(update, context, index)

# Command handler for /search command to get more results
async def search_command(update: Update, context: CallbackContext) -> None:
    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("🛑 Please provide a song name to search, e.g., /search Believer")
        return

    loading_message = await update.message.reply_text("🔍 Searching for more songs...")
    song_data = get_spotify_song(query)

    if song_data:
        reply_text = "*🎶 Additional Results:*\n\n"
        keyboard = []
        for idx, song in enumerate(song_data[:3], start=1):
            button = InlineKeyboardButton(
                f"🔊 {song['song_name']} by {song['artist_name']}",
                callback_data=f"download_{idx-1}"
            )
            keyboard.append([button])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(reply_text, parse_mode='Markdown', reply_markup=reply_markup)

        # Cache song data globally for the user
        user_song_data[update.effective_user.id] = song_data
    else:
        await update.message.reply_text("❌ No additional results found.")
    
    await context.bot.delete_message(chat_id=loading_message.chat_id, message_id=loading_message.message_id)

# Command handler for welcome message and help information
async def start(update: Update, context: CallbackContext) -> None:
    welcome_message = (
        "👋 Welcome to the group! This bot can search and download songs. "
        "Use /song <song name> to find a song or /search for more options.\n"
        "For assistance, contact @marvelona2."
    )
    await update.message.reply_text(welcome_message)

# Main function to run the bot
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('song', song_command))
    application.add_handler(CommandHandler('search', search_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
