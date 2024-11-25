import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from dotenv import load_dotenv
import tempfile
import logging

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
LAST_FM_API_KEY = os.getenv('LAST_FM_API_KEY')
ALLOWED_CHAT_ID = int(os.getenv('ALLOWED_CHAT_ID', '-1002363559013'))

if not TELEGRAM_BOT_TOKEN or not LAST_FM_API_KEY:
    raise EnvironmentError("Environment variables TELEGRAM_BOT_TOKEN and LAST_FM_API_KEY are required.")

# API Endpoints
SPOTIFY_API = "https://spotifyapi.nepdevsnepcoder.workers.dev/?songname={query}"
JIOSAAVN_API = "https://jiosaavn-api-codyandersan.vercel.app/search/all?query={query}&page=1&limit=6"
LAST_FM_API = "http://ws.audioscrobbler.com/2.0/"

# Dictionary to cache user-specific data
user_song_data = {}

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        logger.error(f"Error fetching song data: {e}")
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
        logger.error(f"Last.fm API error: {e}")
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
                    temp_file_path = os.path.join(tempfile.gettempdir(), f"{song['song_name']}.mp3")
                    with open(temp_file_path, 'wb') as temp_file:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            temp_file.write(chunk)

                    await query.message.reply_audio(
                        audio=open(temp_file_path, 'rb'),
                        caption="Powered by ASI Music"
                    )
                    os.remove(temp_file_path)
                else:
                    await query.message.reply_text("❌ Unable to download the song. Please try again later.")
        except Exception as e:
            logger.error(f"Download error: {e}")
            await query.message.reply_text("❌ Error downloading the song. Please try again later.")

# Fetch artist info from Last.fm API
async def artist_command(update: Update, context: CallbackContext) -> None:
    artist_name = ' '.join(context.args)
    if not artist_name:
        await update.message.reply_text("🛑 Provide an artist name, e.g., `/artist Eminem`.")
        return

    await update.message.reply_text(f"🔍 Searching for artist '{artist_name}'...")
    try:
        data = call_lastfm_api('artist.getinfo', {'artist': artist_name})
        artist = data.get('artist', {})

        if artist:
            name = artist.get('name', 'Unknown')
            bio = artist.get('bio', {}).get('summary', 'No biography available.')
            listeners = artist.get('stats', {}).get('listeners', 'Unknown')
            playcount = artist.get('stats', {}).get('playcount', 'Unknown')
            tags = ', '.join(tag['name'] for tag in artist.get('tags', {}).get('tag', []))

            message = (
                f"🎤 *{name}*\n"
                f"👥 Listeners: {listeners}\n"
                f"🎵 Playcount: {playcount}\n"
                f"🏷 Tags: {tags}\n"
                f"📖 Biography:\n{bio}"
            )
            await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await update.message.reply_text(f"❌ No information found for artist '{artist_name}'.")
    except Exception as e:
        logger.error(f"Error fetching artist info: {e}")
        await update.message.reply_text("❌ Error fetching artist information. Please try again later.")

# Fetch top tracks globally or by artist
async def top_tracks_command(update: Update, context: CallbackContext) -> None:
    artist_name = ' '.join(context.args)
    if artist_name:
        await update.message.reply_text(f"🔍 Searching for top tracks by '{artist_name}'...")
        try:
            data = call_lastfm_api('artist.gettoptracks', {'artist': artist_name})
            top_tracks = data.get('toptracks', {}).get('track', [])[:10]

            if top_tracks:
                message = f"🎶 *Top tracks by {artist_name}:*\n"
                for i, track in enumerate(top_tracks, 1):
                    message += f"{i}. {track['name']} ({track['playcount']} plays)\n"
                await update.message.reply_text(message, parse_mode="Markdown")
            else:
                await update.message.reply_text(f"❌ No top tracks found for artist '{artist_name}'.")
        except Exception as e:
            logger.error(f"Error fetching top tracks by artist: {e}")
            await update.message.reply_text("❌ Error fetching top tracks. Please try again later.")
    else:
        await update.message.reply_text("🔍 Fetching top global tracks...")
        try:
            data = call_lastfm_api('chart.gettoptracks', {})
            top_tracks = data.get('tracks', {}).get('track', [])[:10]

            if top_tracks:
                message = "🌍 *Top global tracks:*\n"
                for i, track in enumerate(top_tracks, 1):
                    artist = track['artist']['name']
                    name = track['name']
                    listeners = track.get('listeners', 'N/A')
                    message += f"{i}. {name} by {artist} ({listeners} listeners)\n"
                await update.message.reply_text(message, parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ No global top tracks found.")
        except Exception as e:
            logger.error(f"Error fetching global top tracks: {e}")
            await update.message.reply_text("❌ Error fetching global top tracks. Please try again later.")

async def help_command(update: Update, context: CallbackContext) -> None:
    help_text = (
        "🤖 *ASI Music Bot Commands:*\n\n"
        "🎵 `/search <song>` - Search and download songs.\n"
        "ℹ️ Contact @marvelona2 for support.\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def similar_command(update: Update, context: CallbackContext) -> None:
    track_name = ' '.join(context.args)
    if not track_name:
        await update.message.reply_text("🛑 Provide a track name, e.g., `/similar Believer`")
        return

    await update.message.reply_text(f"🔍 Searching for tracks similar to '{track_name}'...")
    try:
        data = call_lastfm_api('track.getsimilar', {'track': track_name})
        similar_tracks = data.get('similartracks', {}).get('track', [])[:5]
        if similar_tracks:
            message = f"🎶 *Tracks similar to {track_name}:*\n"
            for track in similar_tracks:
                message += f"- {track['name']} by {track['artist']['name']}\n"
            await update.message.reply_text(message, parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ No similar tracks found.")
    except Exception as e:
        logger.error(f"Error fetching similar tracks: {e}")
        await update.message.reply_text("❌ Error fetching similar tracks. Please try again later.")

# Main function
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler('search', search_command))
    application.add_handler(CommandHandler('artist', artist_command))
    application.add_handler(CommandHandler('toptracks', top_tracks_command))
    application.add_handler(CommandHandler('similar', similar_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Starting the bot...")
    application.run_polling()

if __name__ == '__main__':
    main()
