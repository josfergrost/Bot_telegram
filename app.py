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
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY") # Asegúrate de que tu llave 8c854f... esté en Render
PORT = int(os.getenv("PORT", 8080)) 

if not TOKEN:
    raise ValueError("🚨 ERROR: No se encontró el TELEGRAM_TOKEN.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Bot RapidAPI All-In-One activo! Mándame el enlace.")

async def descargar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url_original = update.message.text
    chat_id = update.message.chat_id
    
    if not url_original.startswith(("http://", "https://")):
        return

    mensaje_estado = await update.message.reply_text("Consultando API dedicada... ⏳")
    video_url = None

    # ==========================================
    # MOTOR 1: RapidAPI (Social Download All In One)
    # ==========================================
    if RAPIDAPI_KEY:
        try:
            api_url = "https://social-download-all-in-one.p.rapidapi.com/v1/social/autolink"
            
            payload = {"url": url_original}
            headers = {
                "content-type": "application/json",
                "x-rapidapi-host": "social-download-all-in-one.p.rapidapi.com",
                "x-rapidapi-key": RAPIDAPI_KEY
            }
            
            res = requests.post(api_url, json=payload, headers=headers, timeout=15)
            
            if res.status_code == 200:
                data = res.json()
                logging.info(f"Respuesta cruda de la API: {data}") # <- Revisa esto en los logs de Render
                
                # Intentamos extraer el enlace del JSON basándonos en estructuras comunes
                if "medias" in data and len(data["medias"]) > 0:
                    video_url = data["medias"][0].get("url") or data["medias"][0].get("link")
                elif "video" in data:
                    video_url = data.get("video")
                elif "url" in data:
                    video_url = data.get("url")
                    
                if video_url:
                    logging.info("Video extraído exitosamente de la API.")
            else:
                logging.warning(f"RapidAPI falló con status {res.status_code}: {res.text}")
                
        except Exception as e:
            logging.error(f"Error de conexión con la API: {e}")

    # ==========================================
    # MOTOR 2: yt-dlp (Respaldo)
    # ==========================================
    if not video_url:
        await mensaje_estado.edit_text("La API falló. Intentando con motor de respaldo... ⚙️")
        try:
            ydl_opts = {
                'quiet': True,
                'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url_original, download=False)
                if info:
                    video_url = info.get('url') or (info.get('entries') and info['entries'][0].get('url'))
        except Exception as e:
            logging.error(f"yt-dlp falló: {e}")

    # ==========================================
    # DESCARGA Y ENVÍO CON ARIA2
    # ==========================================
    if not video_url:
        await mensaje_estado.edit_text("Imposible extraer el video. ❌")
        return

    try:
        filename = f"{chat_id}_video.mp4"
        await mensaje_estado.edit_text("Acelerando descarga con aria2... 🚀")
        
        subprocess.run(["aria2c", "--user-agent", "Mozilla/5.0", "-x", "8", "-s", "8", "-o", filename, video_url], check=True)

        await mensaje_estado.edit_text("Subiendo a Telegram... 📤")
        
        with open(filename, 'rb') as video_file:
            await update.message.reply_video(video=video_file)
            
        os.remove(filename)
        await mensaje_estado.delete()
        
    except Exception as e:
        logging.error(f"Error al descargar/enviar: {e}")
        await mensaje_estado.edit_text("Fallo durante la descarga del archivo. 😵")
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
