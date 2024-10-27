import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
import tempfile

# Telegram bot token from environment variable
TELEGRAM_BOT_TOKEN = '7064086507:AAFYD6ujyjknKvEy7xbnAIcZiUNfIojtgvo'

# Function to fetch song details from the Spotify Music Downloader API
def get_spotify_song(song_name):
    query = song_name.replace(' ', '+')
    api_url = f"https://spotifyapi.nepdevsnepcoder.workers.dev/?songname={query}"
    
    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            data = response.json()
            if data:
                return data  # Return all results
            else:
                return None
        else:
            return None
    except Exception as e:
        print(f"Error fetching song details: {e}")
        return None

# Command handler for the /song command
async def song_command(update: Update, context: CallbackContext) -> None:
    if context.args:
        query = ' '.join(context.args)
        song_data = get_spotify_song(query)
        
        if song_data:
            top_results = song_data[:3]
            reply_text = "*🎶 Top Results:*\n\n"
            keyboard = []

            # Create inline buttons for each song download link
            for idx, song in enumerate(top_results, start=1):
                button = InlineKeyboardButton(
                    f"🔊 {song['song_name']} by {song['artist_name']}", 
                    callback_data=f"download_{idx-1}"
                )
                keyboard.append([button])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(reply_text, parse_mode='Markdown', reply_markup=reply_markup)
            context.user_data['song_data'] = top_results
        else:
            await update.message.reply_text("❌ No results found for your query.")
    else:
        await update.message.reply_text("🛑 Please provide a song name to search for, e.g., /song Believer")

# Function to handle downloading the song
async def download_song(update: Update, context: CallbackContext, index: int) -> None:
    if 'song_data' in context.user_data:
        song_data = context.user_data['song_data'][index]
        download_link = song_data['download_link']
        song_name = song_data['song_name']
        
        # Download the song using the download link
        try:
            response = requests.get(download_link, stream=True, timeout=10)  # Added a timeout
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name
                
                # Send the downloaded song to the group
                await update.callback_query.message.reply_audio(audio=open(temp_file_path, 'rb'), title=song_name)
                
                # Clean up the temporary file
                os.remove(temp_file_path)

                # Delete previous messages related to the song command
                await context.bot.delete_message(chat_id=update.callback_query.message.chat_id, message_id=update.callback_query.message.message_id)
                await update.callback_query.answer()  # Acknowledge the button press
            else:
                await update.callback_query.message.reply_text("❌ Failed to download the song. Please try again.")
        except Exception as e:
            print(f"Error downloading the song: {e}")
            await update.callback_query.message.reply_text("❌ An error occurred while downloading the song.")

# Callback handler for button presses
async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if query:  # Check if query is not None
        await query.answer()  # Acknowledge the callback query
        index = int(query.data.split('_')[1])  # Extract the song index
        await download_song(update, context, index)

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler('song', song_command))
    application.add_handler(CallbackQueryHandler(button_handler))  # Use CallbackQueryHandler for button presses

    application.run_polling()

if __name__ == '__main__':
    main()
