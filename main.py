import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from dotenv import load_dotenv
import tempfile

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
LAST_FM_API_KEY = os.getenv('LAST_FM_API_KEY')

if not TELEGRAM_BOT_TOKEN or not LAST_FM_API_KEY:
    raise EnvironmentError("Environment variables TELEGRAM_BOT_TOKEN and LAST_FM_API_KEY are required.")

# API Endpoints
SPOTIFY_API = "https://spotifyapi.nepdevsnepcoder.workers.dev/?songname={query}"
JIOSAAVN_API = "https://jiosaavn-api-codyandersan.vercel.app/search/all?query={query}&page=1&limit=6"
LAST_FM_API = "http://ws.audioscrobbler.com/2.0/"

# Dictionary to cache user-specific data
user_song_data = {}

# Fetch song details from APIs
def fetch_song(query):
    query = query.replace(' ', '+')
    try:
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
            if 'results' in data and isinstance(data['results'], list):
                return [
                    {
                        "song_name": result.get('title', 'Unknown'),
                        "artist_name": result.get('primary_artists', 'Unknown'),
                        "download_link": result.get('perma_url', '')
                    }
                    for result in data['results'] if result.get('perma_url')
                ]
    except Exception as e:
        print(f"Error fetching song data: {e}")
    return None

# Call Last.fm API
def call_lastfm_api(method, params):
    try:
        params.update({
            'method': method,
            'api_key': LAST_FM_API_KEY,
            'format': 'json'
        })
        response = requests.get(LAST_FM_API, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Last.fm API error: {e}")
        return {}

async def search_command(update: Update, context: CallbackContext) -> None:
    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("🛑 Please provide a song name, e.g., `/search Believer`.")
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
        await update.message.reply_text("🎶 Select a song to download:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("❌ No results found.")

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
            with requests.get(download_link, stream=True) as response:
                if response.status_code == 200:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            temp_file.write(chunk)
                        temp_file_path = temp_file.name

                    await query.message.reply_audio(
                        audio=open(temp_file_path, 'rb'),
                        caption="Powered by ASI Music"
                    )
                    os.remove(temp_file_path)
                else:
                    await query.message.reply_text("❌ Unable to download the song. Please try again later.")
        except Exception as e:
            print(f"Download error: {e}")
            await query.message.reply_text("❌ Error downloading the song. Please try again later.")

# Add a placeholder for the similar_command
async def similar_command(update: Update, context: CallbackContext) -> None:
    track_name = ' '.join(context.args)
    if not track_name:
        await update.message.reply_text("🛑 Provide a track name, e.g., `/similar Believer`")
        return

    await update.message.reply_text(f"🔍 Searching for tracks similar to '{track_name}'...")
    try:
        data = call_lastfm_api('track.getsimilar', {'track': track_name})
        similar_tracks = data['similartracks']['track'][:5]
        message = f"🎶 *Tracks similar to {track_name}:*\n"
        for track in similar_tracks:
            message += f"- {track['name']} by {track['artist']['name']}\n"
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        print(f"Error fetching similar tracks: {e}")
        await update.message.reply_text("Hi please try the command once more.")

# Main function
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler('search', search_command))
    application.add_handler(CommandHandler('artist', artist_command))
    application.add_handler(CommandHandler('toptracks', top_tracks_command))
    application.add_handler(CommandHandler('similar', similar_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
