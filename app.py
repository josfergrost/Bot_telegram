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
    # MOTOR 1: API Cobalt (Actualizado a v10)
    # ==========================================
    cobalt_apis = [
        "https://api.cobalt.tools/",          # Nuevo endpoint v10
        "https://api.cobalt.tools/api/json",  # Fallback v9
        "https://co.wuk.sh/",
        "https://api.cobalt.my.id/"
    ]
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    payload = {"url": url_limpia}
    
    for api_endpoint in cobalt_apis:
        try:
            res = requests.post(api_endpoint, json=payload, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                
                # Cobalt v10 devuelve la URL directo, v9 usa 'status'
                if data.get("status") != "error":
                    # Soporte para video único o el primer video de un carrusel
                    video_url = data.get("url") or (data.get("picker") and data["picker"][0].get("url"))
                    
                    if video_url:
                        logging.info(f"Éxito en API: {api_endpoint}")
                        break
        except Exception as e:
            logging.warning(f"Timeout en {api_endpoint}, saltando...")
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
                
                # Buscamos la URL directa o dentro de un carrusel (playlist)
                if info:
                    video_url = info.get('url')
                    if not video_url and 'entries' in info and len(info['entries']) > 0:
                        video_url = info['entries'][0].get('url')

                if video_url:
                    logging.info("Video extraído exitosamente vía yt-dlp.")
                else:
                    logging.warning("yt-dlp leyó la página, pero no encontró un archivo de video accesible (Posible muro de Login).")
        except Exception as e:
            logging.error(f"Fallo total en yt-dlp: {e}")

    # ==========================================
    # DESCARGA Y ENVÍO
    # ==========================================
    if not video_url:
        await mensaje_estado.edit_text("No pude extraer el video. El perfil es privado o bloqueó servidores de nube. ❌")
        return

    try:
        filename = f"{chat_id}_video_extraido.mp4"
        await mensaje_estado.edit_text("Descargando a máxima velocidad... 🚀")

        comando_aria = ["aria2c", "-x", "8", "-s", "8", "-o", filename, video_url]
        subprocess.run(comando_aria, check=True)

        await mensaje_estado.edit_text("Subiendo a Telegram... 📤")

        with open(filename, 'rb') as video_file:
            await update.message.reply_video(video=video_file, caption="¡Aquí lo tienes! 😎")

        os.remove(filename)
        await mensaje_estado.delete()

    except Exception as e:
        logging.error(f"Error descargando o subiendo archivo: {e}")
        await mensaje_estado.edit_text("Fallo al descargar o procesar el video. 😵")
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
