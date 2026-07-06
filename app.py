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
    await update.message.reply_text("¡Bot todoterreno activo! Mándame enlaces de donde sea.")

async def descargar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url_original = update.message.text
    chat_id = update.message.chat_id
    
    if not url_original.startswith(("http://", "https://")):
        return

    mensaje_estado = await update.message.reply_text("Desencriptando enlace... ⏳")
    video_url = None
    url_limpia = url_original.split('?')[0]

    # ==========================================
    # MOTOR 1: Redundancia de APIs (Alta Disponibilidad)
    # ==========================================
    # Si un servidor de Cobalt está caído o nos bloquea, saltamos al siguiente
    cobalt_apis = [
        "https://api.cobalt.tools/api/json",
        "https://co.wuk.sh/api/json",
        "https://api.cobalt.my.id/api/json"
    ]
    
    # Nos disfrazamos de un navegador Chrome real en Windows
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://cobalt.tools",
        "Referer": "https://cobalt.tools/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    payload = {"url": url_limpia}
    
    for api_endpoint in cobalt_apis:
        try:
            res = requests.post(api_endpoint, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") != "error":
                    video_url = data.get("url")
                    if video_url:
                        logging.info(f"Video resuelto vía API: {api_endpoint}")
                        break
        except Exception as e:
            logging.warning(f"Fallo en {api_endpoint}, intentando el siguiente...")
            continue

    # ==========================================
    # MOTOR 2: yt-dlp (Respaldo Universal)
    # ==========================================
    if not video_url:
        await mensaje_estado.edit_text("Usando motor de extracción profunda... ⚙️")
        try:
            ydl_opts = {
                'quiet': True, 
                'no_warnings': True,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url_original, download=False)
                video_url = info.get('url')
                logging.info("Video resuelto vía yt-dlp.")
        except Exception as e:
            logging.error(f"Error en yt-dlp: {e}")

    # ==========================================
    # DESCARGA Y ENVÍO
    # ==========================================
    if not video_url:
        await mensaje_estado.edit_text("No pude extraer un video. El perfil es privado o cambió su seguridad. ❌")
        return

    try:
        filename = f"{chat_id}_video_extraido.mp4"
        await mensaje_estado.edit_text("Descargando a máxima velocidad... 🚀")

        comando_aria = ["aria2c", "-x", "8", "-s", "8", "-o", filename, video_url]
        subprocess.run(comando_aria, check=True)

        await mensaje_estado.edit_text("Subiendo a Telegram... 📤")

        with open(filename, 'rb') as video_file:
            await update.message.reply_video(video=video_file, caption="¡Aquí tienes! 😎")

        os.remove(filename)
        await mensaje_estado.delete()

    except Exception as e:
        logging.error(f"Error procesando el archivo: {e}")
        await mensaje_estado.edit_text("Fallo al descargar o enviar el video. 😵")
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
