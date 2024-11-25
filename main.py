import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from dotenv import load_dotenv
import tempfile

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# JioSaavn API as a fallback
SPOTIFY_API = "https://spotifyapi.nepdevsnepcoder.workers.dev/?songname={query}"
JIOSAAVN_API = "https://jiosaavn-api-codyandersan.vercel.app/search/all?query={query}&page=1&limit=6"

# Dictionary to cache user-specific song data
user_song_data = {}

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

# Command handler for /search
async def search_command(update: Update, context: CallbackContext) -> None:
    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("🛑 Please provide a song name, e.g., `/search Believer`", parse_mode="Markdown")
        return

    await update.message.reply_text("🔍 Searching for songs...")
    song_data = fetch_song(query)

    if song_data:
        user_song_data[update.effective_user.id] = song_data[:3]
        keyboard = [
            [InlineKeyboardButton(f"🔊 {song['song_name']} - {song['artist_name']}", callback_data=f"download_{i}")]
            for i, song in enumerate(song_data[:3])
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🎶 Select a song to download:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("❌ No results found.")

# Callback handler for download
async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    if query.data.startswith("download_"):
        user_id = update.effective_user.id
        index = int(query.data.split('_')[1])
        if user_id not in user_song_data or index >= len(user_song_data[user_id]):
            await query.message.reply_text("❌ Song data not found.")
            return

        song = user_song_data[user_id][index]
        download_link = song['download_link']

        try:
            response = requests.get(download_link, stream=True)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                await query.message.reply_audio(
                    audio=open(temp_file_path, 'rb'),
                    caption="Powered by ASI Music"
                )
                os.remove(temp_file_path)
            else:
                await query.message.reply_text("❌ Failed to download the song.")
        except Exception as e:
            print(f"Download error: {e}")
            await query.message.reply_text("❌ An error occurred while downloading the song.")

# Command handler for /help
async def help_command(update: Update, context: CallbackContext) -> None:
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
