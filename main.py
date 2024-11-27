import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from dotenv import load_dotenv
import tempfile

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Define the specific group chat ID
TARGET_GROUP_CHAT_ID = os.getenv('TARGET_GROUP_CHAT_ID')  # Store your group ID here

# APIs
SPOTIFY_API = "https://spotifyapi.nepdevsnepcoder.workers.dev/?songname={query}"
JIOSAAVN_API = "https://jiosaavn-api-codyandersan.vercel.app/search/all?query={query}&page=1&limit=6"

# Global cache for song data per chat
group_song_data = {}

# Fetch song details from APIs
def fetch_song(query):
    query = query.replace(' ', '+')

    # Try Spotify API first
    response = requests.get(SPOTIFY_API.format(query=query))
    if response.status_code == 200:
        data = response.json()
        if data:
            return data

    # Fallback to JioSaavn API
    response = requests.get(JIOSAAVN_API.format(query=query))
    if response.status_code == 200:
        data = response.json()
        if 'results' in data and data['results']:
            return [
                {"song_name": result['title'], "artist_name": result['primary_artists'], "download_link": result['perma_url']}
                for result in data['results']
            ]

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
        # Cache data for the chat
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
        response = requests.get(download_link, stream=True)
        if response.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                temp_file.write(response.content)
                temp_file_path = temp_file.name

            await query.message.reply_audio(
                audio=open(temp_file_path, 'rb'),
                caption=f"🎶 {song['song_name']} - {song['artist_name']}\nPowered by ASI Music"
            )
            os.remove(temp_file_path)
        else:
            await query.message.reply_text("❌ Failed to download the song.")
    except Exception as e:
        print(f"Download error: {e}")
        await query.message.reply_text("❌ An error occurred while downloading the song.")

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

# Main function
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler('search', search_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
