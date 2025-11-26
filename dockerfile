# Usamos Python 3.10 que es más estable para estas librerías
FROM python:3.10-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar FFMPEG
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Instalar librerías con VERSIONES ESPECÍFICAS para evitar conflictos
# Pillow 9.5.0 es obligatorio porque la 10.0 rompió MoviePy
RUN pip install --no-cache-dir \
    moviepy==1.0.3 \
    decorator==4.4.2 \
    Pillow==9.5.0 \
    google-cloud-storage \
    requests \
    numpy

COPY render.py .
COPY run.sh .

RUN chmod +x run.sh

CMD ["./run.sh"]
