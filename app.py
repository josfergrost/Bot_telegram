import os
import subprocess
import logging
import threading
import requests
import asyncio
import re
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
    mensaje_bienvenida = (
        "🤖 **Bot Híbrido Activo**\n\n"
        "1. Envíe un enlace normal (para contenido público).\n"
        "2. Pegue un comando `cURL` completo (para inyectar cookies y bajar contenido privado)."
    )
    await update.message.reply_text(mensaje_bienvenida, parse_mode='Markdown')

async def descargar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    chat_id = update.message.chat_id
    
    es_curl = texto.startswith("curl ")
    url_procesar = texto

    if not (texto.startswith(("http://", "https://")) or es_curl):
        return

    mensaje_estado = await update.message.reply_text("🔄 *Procesando solicitud...*", parse_mode='Markdown')
    video_url = None
    cookie_extraida = ""
    ua_extraido = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"

    # ==========================================
    # PARSEO DE COMANDO cURL (Estilo Bash Script)
    # ==========================================
    if es_curl:
        await mensaje_estado.edit_text("🕵️‍♂️ *Comando cURL detectado. Extrayendo cabeceras...*", parse_mode='Markdown')
        
        # 1. Extraer URL
        match_url = re.search(r"(https?://[^\s'\"]+)", texto)
        if match_url:
            url_procesar = match_url.group(1).replace("\\", "")
        else:
            await mensaje_estado.edit_text("❌ *No se encontró una URL válida en el comando cURL.*", parse_mode='Markdown')
            return
            
        # 2. Extraer Cookie
        match_cookie = re.search(r"(?i)-H\s+['\"]cookie:\s*([^'\"]+)['\"]", texto)
        if match_cookie:
            cookie_extraida = match_cookie.group(1)
            
        # 3. Extraer User-Agent
        match_ua = re.search(r"(?i)-H\s+['\"]user-agent:\s*([^'\"]+)['\"]", texto)
        if match_ua:
            ua_extraido = match_ua.group(1)

    # ==========================================
    # MOTOR 1: RapidAPI (Solo para enlaces normales)
    # ==========================================
    if RAPIDAPI_KEY and not es_curl:
        api_url = "https://social-download-all-in-one.p.rapidapi.com/v1/social/autolink"
        payload = {"url": url_procesar}
        headers = {
            "content-type": "application/json",
            "x-rapidapi-host": "social-download-all-in-one.p.rapidapi.com",
            "x-rapidapi-key": RAPIDAPI_KEY
        }
        
        for intento in range(2):
            try:
                await mensaje_estado.edit_text(f"📡 *Consultando API pública* `[Intento {intento+1}/2]`...", parse_mode='Markdown')
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
                        break
                elif res.status_code in [500, 502, 503, 504]:
                    await asyncio.sleep(2)
                else:
                    break
            except Exception as e:
                logging.error(f"Error RapidAPI: {e}")
                await asyncio.sleep(2)

    # ==========================================
    # MOTOR 2: yt-dlp (Principal para cURL, Respaldo para links normales)
    # ==========================================
    if not video_url:
        if es_curl:
            await mensaje_estado.edit_text("⚙️ *Inyectando sesión privada en motor de extracción...*", parse_mode='Markdown')
        else:
            await mensaje_estado.edit_text("⚠️ *Fallo en API. Ejecutando motor de contingencia...*", parse_mode='Markdown')
            
        try:
            ydl_opts = {
                'quiet': True,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'http_headers': {
                    'User-Agent': ua_extraido
                }
            }
            # ¡Si extrajimos una cookie del chat de Telegram, se la pasamos a yt-dlp!
            if cookie_extraida:
                ydl_opts['http_headers']['Cookie'] = cookie_extraida
                
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url_procesar, download=False)
                if info:
                    video_url = info.get('url') or (info.get('entries') and info['entries'][0].get('url'))
        except Exception as e:
            logging.error(f"yt-dlp falló: {e}")

    # ==========================================
    # VALIDACIÓN DE PRIVACIDAD
    # ==========================================
    if not video_url:
        msg_error = "❌ **Extracción denegada.**\nEl contenido es privado. Utiliza la opción de 'Copiar como cURL' en tu navegador y pega el código aquí."
        await mensaje_estado.edit_text(msg_error, parse_mode='Markdown')
        return

    # ==========================================
    # DESCARGA Y ENVÍO A TELEGRAM
    # ==========================================
    filename = f"{chat_id}_media.mp4"
    try:
        await mensaje_estado.edit_text("⬇️ *Descargando archivo acelerado...*", parse_mode='Markdown')
        
        # Preparamos los argumentos base de aria2c
        comando_aria = ["aria2c", "--user-agent", ua_extraido, "-x", "8", "-s", "8", "-o", filename]
        
        # Si había cookie, se la pasamos a aria2c para que no lo bloqueen en el último paso
        if cookie_extraida:
            comando_aria.extend(["--header", f"Cookie: {cookie_extraida}"])
            
        comando_aria.append(video_url)
        subprocess.run(comando_aria, check=True)

        await mensaje_estado.edit_text("⬆️ *Subiendo a Telegram, por favor espere...*", parse_mode='Markdown')
        
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
                logging.error(f"Intento {intento_subida+1} de subida falló: {e}")
                if intento_subida < 2:
                    await mensaje_estado.edit_text(f"⚠️ *Interrupción de red. Reintentando subida* `[{intento_subida+2}/3]`...", parse_mode='Markdown')
                    await asyncio.sleep(3)
                else:
                    raise e

        if exito_subida:
            await mensaje_estado.delete()

    except Exception as e:
        logging.error(f"Fallo crítico en transferencia: {e}")
        await mensaje_estado.edit_text("🛑 **Error de transferencia.**\nLos servidores excedieron el tiempo de respuesta.", parse_mode='Markdown')
    finally:
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
