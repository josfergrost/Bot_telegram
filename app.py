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
PORT = int(os.getenv("PORT", 8080)) 

if not TOKEN:
    raise ValueError("🚨 ERROR: No se encontró el TELEGRAM_TOKEN.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Bot híbrido activo! Mándame enlaces de cualquier lado.")

async def descargar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url_original = update.message.text
    chat_id = update.message.chat_id
    
    if not url_original.startswith(("http://", "https://")):
        return

    mensaje_estado = await update.message.reply_text("Analizando enlace... ⏳")
    video_url = None
    url_limpia = url_original.split('?')[0]

    # ==========================================
    # MOTOR 1: API Externa (Ideal para Instagram/TikTok)
    # ==========================================
    try:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        payload = {"url": url_limpia}
        res = requests.post("https://api.cobalt.tools/api/json", json=payload, headers=headers, timeout=10)
        
        if res.status_code == 200:
            video_url = res.json().get("url")
            logging.info("Video resuelto vía API externa.")
    except Exception as e:
        logging.warning(f"La API externa falló o tardó demasiado: {e}")

    # ==========================================
    # MOTOR 2: yt-dlp (El respaldo universal para todo lo demás)
    # ==========================================
    if not video_url:
        await mensaje_estado.edit_text("Usando motor de respaldo universal... ⚙️")
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Aquí pasamos la original porque algunas webs sí necesitan los parámetros
                info = ydl.extract_info(url_original, download=False)
                video_url = info.get('url')
                logging.info("Video resuelto vía yt-dlp.")
        except Exception as e:
            logging.error(f"Error en yt-dlp: {e}")

    # Validamos si ambos motores fracasaron
    if not video_url:
        await mensaje_estado.edit_text("No pude extraer un video de este enlace. Puede que sea privado o esté muy protegido. ❌")
        return

    try:
        filename = f"{chat_id}_video_extraido.mp4"
        await mensaje_estado.edit_text("Descargando con aria2... 🚀")

        comando_aria = ["aria2c", "-x", "8", "-s", "8", "-o", filename, video_url]
        subprocess.run(comando_aria, check=True)

        await mensaje_estado.edit_text("Subiendo a Telegram... 📤")

        with open(filename, 'rb') as video_file:
            await update.message.reply_video(video=video_file, caption="¡Ahí lo tienes! 😎")

        os.remove(filename)
        await mensaje_estado.delete()

    except Exception as e:
        logging.error(f"Error procesando el archivo: {e}")
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
