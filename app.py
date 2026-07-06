import os
import subprocess
import logging
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
# Render inyecta automáticamente la variable PORT
PORT = int(os.getenv("PORT", 8080)) 

if not TOKEN:
    raise ValueError("🚨 ERROR: No se encontró el TELEGRAM_TOKEN.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Bot activo desde Render! Manda tu link.")

async def descargar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    chat_id = update.message.chat_id
    
    if not url.startswith(("http://", "https://")):
        return

    mensaje_estado = await update.message.reply_text("Procesando... ⏳")

    try:
        ydl_opts = {'quiet': True, 'no_warnings': True}
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_url = info.get('url')
            title = info.get('title', 'video').replace("/", "_")
            filename = f"{chat_id}_{title}.mp4"

        if not video_url:
            await mensaje_estado.edit_text("Fallo al extraer link directo. ❌")
            return

        await mensaje_estado.edit_text("Descargando con aria2... 🚀")

        comando_aria = ["aria2c", "-x", "8", "-s", "8", "-o", filename, video_url]
        subprocess.run(comando_aria, check=True)

        await mensaje_estado.edit_text("Subiendo a Telegram... 📤")

        with open(filename, 'rb') as video_file:
            await update.message.reply_video(video=video_file, caption="¡Ahí lo tienes! 😎")

        os.remove(filename)
        await mensaje_estado.delete()

    except Exception as e:
        logging.error(f"Error: {e}")
        await mensaje_estado.edit_text("Fallo en la descarga. 😵")
        if 'filename' in locals() and os.path.exists(filename):
            os.remove(filename)

def run_dummy_server():
    server_address = ('0.0.0.0', PORT)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    logging.info(f"Servidor HTTP dummy corriendo en el puerto {PORT}...")
    httpd.serve_forever()

def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, descargar_video))
    
    logging.info("Iniciando Polling a Telegram...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
