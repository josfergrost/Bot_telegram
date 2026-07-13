import os
import subprocess
import logging
import threading
import asyncio
import requests
import shutil
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("RAPIDAPI_KEY") or os.getenv("ZM_API_KEY") 
PORT = int(os.getenv("PORT", 8080)) 

# Rutas de los archivos
SECRET_COOKIE_FILE = "/etc/secrets/cookies.txt"
WORKING_COOKIE_FILE = "/tmp/cookies.txt"

# Copiar el archivo secreto a un directorio con permisos de escritura
if os.path.exists(SECRET_COOKIE_FILE):
    try:
        shutil.copy2(SECRET_COOKIE_FILE, WORKING_COOKIE_FILE)
        logging.info("Archivo de cookies copiado a /tmp/ exitosamente.")
    except Exception as e:
        logging.error(f"Error copiando cookies: {e}")

if not TOKEN:
    raise ValueError("🚨 ERROR: No se encontró el TELEGRAM_TOKEN.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje_bienvenida = (
        "🤖 **Bot de Extracción con Sesión Activo**\n\n"
        "Sistema listo. Motor local optimizado para evadir firewalls de Meta."
    )
    await update.message.reply_text(mensaje_bienvenida, parse_mode='Markdown')

async def descargar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url_original = update.message.text.strip()
    chat_id = update.message.chat_id
    
    if not url_original.startswith(("http://", "https://")):
        return

    mensaje_estado = await update.message.reply_text("🔄 *Analizando petición...*", parse_mode='Markdown')
    video_url = None

    # Ruteo Inteligente: Si es Instagram y tenemos cookies editables, vamos directo con yt-dlp
    es_instagram_con_sesion = "instagram.com" in url_original and os.path.exists(WORKING_COOKIE_FILE)

    # ==========================================
    # MOTOR 1: API Dedicada (Para todo menos IG local)
    # ==========================================
    if API_KEY and not es_instagram_con_sesion:
        await mensaje_estado.edit_text("📡 *Consultando API principal...*", parse_mode='Markdown')
        try:
            api_url = "https://social-download-all-in-one.p.rapidapi.com/v1/social/autolink"
            payload = {"url": url_original}
            headers = {
                "content-type": "application/json",
                "x-rapidapi-host": "social-download-all-in-one.p.rapidapi.com",
                "x-rapidapi-key": API_KEY
            }
            
            for intento in range(2):
                res = requests.post(api_url, json=payload, headers=headers, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    if "medias" in data and len(data["medias"]) > 0:
                        video_url = data["medias"][0].get("url") or data["medias"][0].get("link")
                    elif "video" in data:
                        video_url = data.get("video")
                    elif "url" in data:
                        video_url = data.get("url")
                        
                    if video_url:
                        logging.info("Éxito usando la API principal.")
                        break
                elif res.status_code in [500, 502, 503, 504]:
                    await asyncio.sleep(2)
        except Exception as e:
            logging.error(f"Fallo en API principal: {e}")

    # ==========================================
    # MOTOR 2: yt-dlp (Principal para IG, Respaldo para el resto)
    # ==========================================
    if not video_url:
        if es_instagram_con_sesion:
            await mensaje_estado.edit_text("🔑 *Sesión detectada. Extrayendo desde motor local...*", parse_mode='Markdown')
        else:
            await mensaje_estado.edit_text("⚠️ *Fallo en la red. Intentando motor de respaldo...*", parse_mode='Markdown')
            
        try:
           ydl_opts = {
                'quiet': False,
                'verbose': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            }
            # Inyectamos la copia editable del archivo de texto a yt-dlp
            if os.path.exists(WORKING_COOKIE_FILE):
                ydl_opts['cookiefile'] = WORKING_COOKIE_FILE

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url_original, download=False)
                if info:
                    video_url = info.get('url') or (info.get('entries') and info['entries'][0].get('url'))
                    if video_url:
                        logging.info("Resuelto exitosamente vía yt-dlp local.")
        except Exception as e:
            logging.error(f"yt-dlp no pudo extraer el enlace localmente: {e}")

    # ==========================================
    # VALIDACIÓN FINAL
    # ==========================================
    if not video_url:
        msg_error = "❌ **Extracción denegada.**\nEl contenido es privado o caducó."
        await mensaje_estado.edit_text(msg_error, parse_mode='Markdown')
        return

    # ==========================================
    # DESCARGA Y ENVÍO A TELEGRAM
    # ==========================================
    filename = f"{chat_id}_media.mp4"
    try:
        await mensaje_estado.edit_text("⬇️ *Descargando archivo acelerado...*", parse_mode='Markdown')
        
        comando_aria = ["aria2c", "--user-agent", "Mozilla/5.0", "-x", "8", "-s", "8", "-o", filename]
        
        # Le pasamos la copia editable a aria2c también
        if os.path.exists(WORKING_COOKIE_FILE):
            comando_aria.extend(["--load-cookies", WORKING_COOKIE_FILE])
            
        comando_aria.append(video_url)
        subprocess.run(comando_aria, check=True)

        await mensaje_estado.edit_text("⬆️ *Subiendo a Telegram...*", parse_mode='Markdown')
        
        exito_subida = False
        for intento_subida in range(3):
            try:
                with open(filename, 'rb') as video_file:
                    await update.message.reply_video(
                        video=video_file, 
                        caption="✅ **Procesamiento completado**",
                        parse_mode='Markdown',
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=60
                    )
                exito_subida = True
                break
            except Exception as e:
                if intento_subida < 2:
                    await mensaje_estado.edit_text(f"⚠️ *Interrupción de red. Reintentando subida* `[{intento_subida+2}/3]`...", parse_mode='Markdown')
                    await asyncio.sleep(3)
                else:
                    raise e

        if exito_subida:
            await mensaje_estado.delete()

    except Exception as e:
        logging.error(f"Fallo en transferencia: {e}")
        await mensaje_estado.edit_text("🛑 **Error de transferencia.**\nTiempo de respuesta excedido.", parse_mode='Markdown')
    finally:
        if 'filename' in locals() and os.path.exists(filename):
            os.remove(filename)

def run_dummy_server():
    server_address = ('0.0.0.0', PORT)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    logging.info(f"Servidor dummy en el puerto {PORT}...")
    httpd.serve_forever()

def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, descargar_video))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
