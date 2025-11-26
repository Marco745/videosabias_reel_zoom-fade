import os
import requests
from moviepy.editor import *
from google.cloud import storage
import traceback
import sys
from PIL import Image
import numpy as np

# --- CONFIGURACIÓN ---
WIDTH = 1080
HEIGHT = 1920
FADE_DURATION = 0.5 
ZOOM_FACTOR = 1.30

def download_file(url, filename):
    print(f"Descargando: {url} -> {filename}")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    except Exception as e:
        print(f"!!! ERROR DESCARGANDO {url}: {e}")
        raise e

def zoom_effect(clip, zoom_ratio=ZOOM_FACTOR):
    def effect(get_frame, t):
        img = get_frame(t)
        h, w = img.shape[:2]
        
        # Zoom progresivo basado en el tiempo
        current_zoom = 1 + (zoom_ratio - 1) * (t / clip.duration)
        
        new_w = int(w / current_zoom)
        new_h = int(h / current_zoom)
        x1 = int((w - new_w) / 2)
        y1 = int((h - new_h) / 2)
        x2 = x1 + new_w
        y2 = y1 + new_h
        
        # Recorte y redimensionado
        cropped_img = img[y1:y2, x1:x2]
        pil_img = Image.fromarray(cropped_img)
        resized_img = pil_img.resize((w, h), Image.LANCZOS)
        return np.array(resized_img)
        
    return clip.fl(effect)

def upload_to_gcs(local_path, bucket_name, destination_blob_name):
    try:
        print(f"Subiendo: {local_path} a {bucket_name}")
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(local_path)
        public_url = f"https://storage.googleapis.com/{bucket_name}/{destination_blob_name}"
        print(f"PUBLIC_URL={public_url}")
        return public_url
    except Exception as e:
        print(f"ERROR UPLOAD: {e}")
        return None

def main():
    try:
        print("--- INICIANDO RENDER V4 (TIMELINE FIX) ---")
        
        images_str = os.environ.get('IMAGES', '').strip()
        audios_str = os.environ.get('AUDIOS', '').strip()
        output_bucket = os.environ.get('OUTPUT_BUCKET', '').strip()
        output_filename = os.environ.get('OUTPUT_FILENAME', 'video_output.mp4').strip()

        if not images_str or not audios_str:
            print("ERROR: Faltan variables IMAGES o AUDIOS")
            return

        image_urls = [url.strip() for url in images_str.split(',') if url.strip()]
        audio_urls = [url.strip() for url in audios_str.split(',') if url.strip()]

        os.makedirs('temp_imgs', exist_ok=True)
        os.makedirs('temp_audios', exist_ok=True)

        final_clips = []
        img_index = 0

        # --- BUCLE DE ESCENAS ---
        for i, audio_url in enumerate(audio_urls):
            print(f"--- Procesando Escena {i+1} ---")
            
            # 1. Preparar Audio
            audio_path = f"temp_audios/scene_{i}.mp3"
            download_file(audio_url, audio_path)
            
            try:
                audio_clip = AudioFileClip(audio_path)
            except Exception as e:
                print(f"ERROR leyendo audio: {e}")
                raise e

            scene_duration = audio_clip.duration
            
            # Calculamos cuánto debe durar cada imagen (mitad del audio)
            slot_duration = scene_duration / 2
            
            scene_image_clips = []

            # 2. Preparar Imágenes (Bucle de 2)
            for j in range(2):
                if img_index >= len(image_urls): break
                
                img_path = f"temp_imgs/img_{img_index}.jpg"
                download_file(image_urls[img_index], img_path)

                # A. Crear clip base
                # Le damos un poco más de duración (+FADE_DURATION) para que se solape bien
                this_img_duration = slot_duration + FADE_DURATION
                
                img_clip = (ImageClip(img_path)
                            .resize(height=HEIGHT)
                            .crop(x_center=WIDTH/2, y_center=HEIGHT/2, width=WIDTH, height=HEIGHT)
                            .set_duration(this_img_duration)
                            .set_fps(30))

                # B. Efecto Zoom
                zoom_amt = ZOOM_FACTOR if j == 0 else ZOOM_FACTOR + 0.05
                img_clip = zoom_effect(img_clip, zoom_ratio=zoom_amt)
                
                # C. POSICIONAMIENTO EN EL TIEMPO (LA SOLUCIÓN AL PANTALLA NEGRA)
                if j == 0:
                    # Imagen 1: Empieza en 0
                    start_time = 0
                    img_clip = img_clip.set_start(start_time)
                else:
                    # Imagen 2: Empieza cuando acaba el slot de la 1, MENOS el tiempo de fade
                    # Esto hace que se monten una encima de otra
                    start_time = slot_duration - FADE_DURATION
                    img_clip = img_clip.set_start(start_time).crossfadein(FADE_DURATION)

                scene_image_clips.append(img_clip)
                img_index += 1

            # 3. Componer Escena
            # CompositeVideoClip usará los tiempos de inicio que definimos arriba
            scene_video = CompositeVideoClip(scene_image_clips)
            
            # Cortar exactamente al final del audio (por si sobra un poco de imagen)
            scene_video = scene_video.set_duration(scene_duration).set_audio(audio_clip)
            
            final_clips.append(scene_video)

        # --- RENDER FINAL ---
        print("Renderizando video final...")
        final_video = concatenate_videoclips(final_clips, method="compose")
        local_output = "output.mp4"
        
        final_video.write_videofile(
            local_output, fps=30, codec='libx264', audio_codec='aac', bitrate='8000k', preset='medium', threads=4
        )

        if output_bucket:
            upload_to_gcs(local_output, output_bucket, output_filename)
        else:
            print("No se definió bucket de salida.")

    except Exception:
        print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("ERROR CRÍTICO EN EL SCRIPT:")
        traceback.print_exc()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
