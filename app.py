import os
import subprocess
import logging
import threading
import requests
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
PORT = int(os.getenv("PORT", 8080)) 

if not TOKEN:
    raise ValueError("🚨 ERROR: No se encontró el TELEGRAM_TOKEN.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Bot blindado con RapidAPI activo! Mándame tu enlace.")

async def descargar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url_original = update.message.text
    chat_id = update.message.chat_id
    
    if not url_original.startswith(("http://", "https://")):
        return

    mensaje_estado = await update.message.reply_text("Interconectando con API dedicada... ⏳")
    video_url = None
    url_limpia = url_original.split('?')[0]

    # ==========================================
    # MOTOR 1: RapidAPI (Anti-Firewalls)
    # ==========================================
    if RAPIDAPI_KEY:
        try:
            api_url = "https://social-media-video-downloader.p.rapidapi.com/smvd/get/all"
            querystring = {"url": url_original}
            headers = {
                "x-rapidapi-key": RAPIDAPI_KEY,
                "x-rapidapi-host": "social-media-video-downloader.p.rapidapi.com"
            }
            
            res = requests.get(api_url, headers=headers, params=querystring, timeout=15)
            
            if res.status_code == 200:
                data = res.json()
                # Navegamos el JSON de esta API específica para sacar el link del MP4
                if "links" in data and len(data["links"]) > 0:
                    video_url = data["links"][0].get("link")
                    if video_url:
                        logging.info("Éxito extrayendo video vía RapidAPI.")
            else:
                logging.warning(f"RapidAPI devolvió status {res.status_code}")
                
        except Exception as e:
            logging.error(f"Fallo en conexión con RapidAPI: {e}")

    # ==========================================
    # MOTOR 2: yt-dlp (Respaldo Universal)
    # ==========================================
    if not video_url:
        await mensaje_estado.edit_text("Usando motor de respaldo (yt-dlp)... ⚙️")
        try:
            ydl_opts = {
                'quiet': True, 
                'no_warnings': True,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url_original, download=False)
                if info:
                    video_url = info.get('url')
                    if not video_url and 'entries' in info and len(info['entries']) > 0:
                        video_url = info['entries'][0].get('url')
        except Exception as e:
            logging.error(f"Error en yt-dlp: {e}")

    # ==========================================
    # DESCARGA Y ENVÍO
    # ==========================================
    if not video_url:
        await mensaje_estado.edit_text("Los protocolos de seguridad del sitio bloquearon la extracción. ❌")
        return

    try:
        filename = f"{chat_id}_video.mp4"
        await mensaje_estado.edit_text("Descargando archivo con aria2... 🚀")

        comando_aria = ["aria2c", "-x", "8", "-s", "8", "-o", filename, video_url]
        subprocess.run(comando_aria, check=True)

        await mensaje_estado.edit_text("Subiendo a Telegram... 📤")

        with open(filename, 'rb') as video_file:
            await update.message.reply_video(video=video_file, caption="¡Descarga completada! 😎")

        os.remove(filename)
        await mensaje_estado.delete()

    except Exception as e:
        logging.error(f"Error descargando o subiendo archivo: {e}")
        await mensaje_estado.edit_text("Fallo al procesar o subir el video final. 😵")
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
