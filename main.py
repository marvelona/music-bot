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

# API Endpoints
SPOTIFY_API = "https://spotifyapi.nepdevsnepcoder.workers.dev/?songname={query}"
JIOSAAVN_API = "https://jiosaavn-api-codyandersan.vercel.app/search/all?query={query}&page=1&limit=6"
LAST_FM_API = "http://ws.audioscrobbler.com/2.0/"

# Dictionary to cache user-specific data
user_song_data = {}
user_artist_data = {}

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

# Call Last.fm API
def call_lastfm_api(method, params):
    params.update({
        'method': method,
        'api_key': LAST_FM_API_KEY,
        'format': 'json'
    })
    response = requests.get(LAST_FM_API, params=params)
    response.raise_for_status()
    return response.json()

async def artist_command(update: Update, context: CallbackContext) -> None:
    artist_name = ' '.join(context.args)
    if not artist_name:
        await update.message.reply_text("🛑 Please provide an artist name, e.g., `/artist Imagine Dragons`")
        return

    await update.message.reply_text(f"🔍 Fetching info for artist '{artist_name}'...")
    await fetch_artist_info(update, artist_name)

async def top_tracks_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("🔍 Fetching trending tracks...")
    try:
        data = call_lastfm_api('chart.gettoptracks', {})
        tracks = data['tracks']['track'][:5]
        message = "🎶 *Trending Tracks:*\n"
        for track in tracks:
            message += f"- {track['name']} by {track['artist']['name']}\n"
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        print(f"Error fetching top tracks: {e}")
        await update.message.reply_text("Hi please try the command once more.")

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

# Callback handler for buttons
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
                await query.message.reply_text("Hi please try the command once more.")
        except Exception as e:
            print(f"Download error: {e}")
            await query.message.reply_text("Hi please try the command once more.")

    elif query.data.startswith("artist_"):
        artist_name = query.data.split('_', 1)[1]
        await fetch_artist_info(update, artist_name)

# Fetch artist information
async def fetch_artist_info(update: Update, artist_name: str) -> None:
    await update.callback_query.message.reply_text(f"🔍 Searching for artist '{artist_name}'...")
    try:
        data = call_lastfm_api('artist.getinfo', {'artist': artist_name})
        artist = data['artist']
        message = (
            f"🎤 *{artist['name']}*\n"
            f"🌟 Listeners: {artist['stats']['listeners']}\n"
            f"🎧 Play Count: {artist['stats']['playcount']}\n\n"
            f"🔗 [More Info]({artist['url']})"
        )
        top_tracks = artist.get('toptracks', {}).get('track', [])
        keyboard = [
            [InlineKeyboardButton(f"🎵 {track['name']}", callback_data=f"download_{track['name']}")]
            for track in top_tracks[:3]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.callback_query.message.reply_text(message, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        print(f"Error fetching artist info: {e}")
        await update.callback_query.message.reply_text("Hi please try the command once more.")

# Command handler for /help
async def help_command(update: Update, context: CallbackContext) -> None:
    help_text = (
        "🤖 *ASI Music Bot Commands:*\n\n"
        "🎵 `/search <song>` - Search and download songs.\n"
        "🌟 `/toptracks` - Get trending tracks.\n"
        "🔁 `/similar <track>` - Find similar tracks.\n"
        "🎤 `/artist <name>` - Get artist information.\n"
        "ℹ️ Contact @marvelona2 for support.\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# Main function
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler('search', search_command))

    # Add Last.fm commands for artist, toptracks, and similar
    application.add_handler(CommandHandler('artist', artist_command))
    application.add_handler(CommandHandler('toptracks', top_tracks_command))
    application.add_handler(CommandHandler('similar', similar_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
