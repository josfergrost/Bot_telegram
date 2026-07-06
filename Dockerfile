FROM python:3.10-slim

# Instalar aria2, ffmpeg y herramientas del sistema
RUN apt-get update && apt-get install -y \
    aria2 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# Copiar requerimientos e instalar
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copiar el resto del código
COPY . .

# Comando para arrancar el bot
CMD ["python", "app.py"]
