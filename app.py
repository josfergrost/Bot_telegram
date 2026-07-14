import os
import subprocess
import logging
import threading
import asyncio
import requests
import shutil
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

# Configuración de logs
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Variables de entorno
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("RAPIDAPI_KEY") or os.getenv("ZM_API_KEY") 
PORT = int(os.getenv("PORT", 8080)) 
EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", f"http://localhost:{PORT}") 

SECRET_COOKIE_FILE = "/etc/secrets/cookies.txt"
WORKING_COOKIE_FILE = "/tmp/cookies.txt"

# Preparación de cookies seguras
if os.path.exists(SECRET_COOKIE_FILE):
    try:
        shutil.copy2(SECRET_COOKIE_FILE, WORKING_COOKIE_FILE)
        logging.info("Archivo de cookies copiado a /tmp/ exitosamente.")
    except Exception as e:
        logging.error(f"Error copiando cookies: {e}")

if not TOKEN:
    raise ValueError("🚨 ERROR: No se encontró el TELEGRAM_TOKEN.")

# Lista VIP para evitar gasto de API
DOMINIOS_LOCALES = ["instagram.com", "tiktok.com", "twitter.com", "x.com"]

# Función de auto-limpieza para los videos pesados alojados en el CDN temporal
async def programar_autodestruccion(filepath, delay_seconds=3600):
    await asyncio.sleep(delay_seconds)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            logging.info(f"🗑️ Archivo temporal pesado eliminado: {filepath}")
        except Exception as e:
            logging.error(f"No se pudo borrar {filepath}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje_bienvenida = (
        "🤖 **Bot de Extracción Multi-Plataforma Activo**\n\n"
        "Sistema con CDN híbrido multi-hilo listo. Envíe un enlace."
    )
    await update.message.reply_text(mensaje_bienvenida, parse_mode='Markdown')

async def descargar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url_original = update.message.text.strip()
    chat_id = update.message.chat_id
    
    if not url_original.startswith(("http://", "https://")):
        return

    mensaje_estado = await update.message.reply_text("🔄 *Analizando petición...*", parse_mode='Markdown')
    
    video_url = None
    descarga_lista_en_disco = False
    
    # Identificador único para evitar colisiones de archivos simultáneos
    codigo_unico = uuid.uuid4().hex[:6]
    filename = f"{chat_id}_{codigo_unico}_media.mp4"

    es_dominio_local = any(dom in url_original for dom in DOMINIOS_LOCALES) and os.path.exists(WORKING_COOKIE_FILE)

    # ==========================================
    # MOTOR 1: API Dedicada (RapidAPI)
    # ==========================================
    if API_KEY and not es_dominio_local:
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
    # MOTOR 2: yt-dlp (Descarga Directa con Sesión)
    # ==========================================
    if not video_url:
        if es_dominio_local:
            await mensaje_estado.edit_text("🔑 *Sesión VIP detectada. Extrayendo calidad original...*", parse_mode='Markdown')
        else:
            await mensaje_estado.edit_text("⚠️ *Fallo en la red. Intentando motor local de respaldo...*", parse_mode='Markdown')
            
        try:
            ydl_opts = {
                'quiet': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': filename,
                'merge_output_format': 'mp4'
            }
            if os.path.exists(WORKING_COOKIE_FILE):
                ydl_opts['cookiefile'] = WORKING_COOKIE_FILE

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url_original])
                
                if os.path.exists(filename):
                    descarga_lista_en_disco = True
                    logging.info("Resuelto y descargado exitosamente vía yt-dlp.")
        except Exception as e:
            logging.error(f"yt-dlp falló la descarga: {e}")

    # ==========================================
    # VALIDACIÓN FINAL
    # ==========================================
    if not video_url and not descarga_lista_en_disco:
        msg_error = "❌ **Extracción denegada.**\nEl contenido es privado, caducó, o la plataforma bloqueó la IP."
        await mensaje_estado.edit_text(msg_error, parse_mode='Markdown')
        return

    # ==========================================
    # DESCARGA ARIA2C Y ENRUTAMIENTO INTELIGENTE
    # ==========================================
    try:
        # Descarga desde la API (si aplica)
        if not descarga_lista_en_disco:
            await mensaje_estado.edit_text("⬇️ *Descargando archivo acelerado...*", parse_mode='Markdown')
            comando_aria = ["aria2c", "--user-agent", "Mozilla/5.0", "-x", "8", "-s", "8", "-o", filename]
            if os.path.exists(WORKING_COOKIE_FILE):
                comando_aria.extend(["--load-cookies", WORKING_COOKIE_FILE])
            comando_aria.append(video_url)
            subprocess.run(comando_aria, check=True)

        # Validación de tamaño del archivo (Límite Telegram: 50MB)
        peso_bytes = os.path.getsize(filename)
        peso_mb = peso_bytes / (1024 * 1024)

        if peso_mb > 49.0:
            # RUTEO CDN: Enlace de descarga forzada directa
            enlace_cdn = f"{EXTERNAL_URL}/{filename}"
            mensaje_cdn = (
                f"🗄️ **Video demasiado pesado para Telegram** ({peso_mb:.1f} MB).\n\n"
                f"🔗 **[DESCARGAR ARCHIVO DIRECTAMENTE]({enlace_cdn})**\n\n"
                f"_El enlace expirará automáticamente en 1 hora por seguridad._"
            )
            await mensaje_estado.edit_text(mensaje_cdn, parse_mode='Markdown')
            
            # Autodestrucción asíncrona (1 hora)
            asyncio.create_task(programar_autodestruccion(filename, 3600))
            
        else:
            # RUTEO CLÁSICO: Subida directa a Telegram
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
                        await mensaje_estado.edit_text(f"⚠️ *Interrupción de red. Reintentando* `[{intento_subida+2}/3]`...", parse_mode='Markdown')
                        await asyncio.sleep(3)
                    else:
                        raise e

            if exito_subida:
                await mensaje_estado.delete()
                # Eliminación inmediata post-subida
                if os.path.exists(filename):
                    os.remove(filename)

    except Exception as e:
        logging.error(f"Fallo general en transferencia: {e}")
        await mensaje_estado.edit_text("🛑 **Error de transferencia.**\nTiempo de respuesta excedido.", parse_mode='Markdown')
        if os.path.exists(filename):
            os.remove(filename)

# ==========================================
# SERVIDOR WEB CDN MULTI-HILO
# ==========================================
class CDNHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Fuerza la descarga (.mp4) y evita que el navegador intente hacer streaming
        if self.path.endswith('.mp4'):
            self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(self.path)}"')
        super().end_headers()

def run_dummy_server():
    server_address = ('0.0.0.0', PORT)
    # ThreadingHTTPServer evita cuelgues (502 Bad Gateway) al procesar descargas
    httpd = ThreadingHTTPServer(server_address, CDNHandler)
    logging.info(f"Servidor HTTP Multi-hilo y CDN activo en el puerto {PORT}...")
    httpd.serve_forever()

def main():
    # Inicia el CDN en un hilo de fondo
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    # Inicia el motor de Telegram
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, descargar_video))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
