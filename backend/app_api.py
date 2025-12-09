# app_api.py — Guarda audios, transcribe con Whisper,
# analiza intención con Qwen2 7B Instruct Q4 (Ollama)
# y envía comandos a un ESP32 usando MQTT (LED + RGB estado de ánimo).

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import os
import subprocess
import json
import textwrap
import time
from typing import Optional

# --- Whisper ---
from whisper_timestamped import load_model, transcribe

# --- MQTT ---
import paho.mqtt.client as mqtt

# ===== CONFIGURACIÓN (variables de entorno con fallback) =====
MQTT_SERVER = os.getenv("MQTT_SERVER", "192.168.0.12")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_LED = os.getenv("MQTT_TOPIC_LED", "casa/esp32/led")
MQTT_TOPIC_RGB = os.getenv("MQTT_TOPIC_RGB", "casa/esp32/rgb")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2:7b-instruct-q4_0")
AUDIO_SAVE_DIR = os.getenv("AUDIO_SAVE_DIR", "/home/abraham/audios_recibidos")
MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "25"))

# Crear cliente MQTT global
mqtt_client = mqtt.Client()

def connect_mqtt():
    try:
        print(f"Intentando conectar a MQTT {MQTT_SERVER}:{MQTT_PORT}...")
        mqtt_client.connect(MQTT_SERVER, MQTT_PORT, 60)
        mqtt_client.loop_start()  # <<< IMPORTANTE: inicia el hilo de red
        print(f"Conectado a MQTT en {MQTT_SERVER}:{MQTT_PORT}")
        return True
    except Exception as e:
        print("ERROR: No se pudo conectar al broker MQTT:", e)
        return False

mqtt_connected = connect_mqtt()

app = FastAPI()

# Permitir acceso desde cualquier dispositivo en la red local (LAN)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # En producción conviene limitar esto
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cargar modelo Whisper una sola vez al iniciar
print("Cargando modelo Whisper (tiny)...")
whisper_model = load_model("tiny")   # puedes cambiar a "base" si quieres más calidad
print("Whisper cargado correctamente.")


@app.get("/")
def root():
    return {"ok": True, "message": "API viva"}


@app.get("/ping")
def ping():
    return {
        "pong": True,
        "mqtt_connected": mqtt_connected,
        "mqtt_server": MQTT_SERVER,
        "model": OLLAMA_MODEL,
    }


def call_ollama_qwen2(prompt: str, timeout: int = 120) -> str:
    """
    Envía el prompt a Ollama usando stdin (echo | ollama run).
    Funciona incluso en versiones sin soporte para -p.
    """
    try:
        process = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "{""error"": ""timeout""}"

    if process.stderr:
        print("OLLAMA STDERR:", process.stderr)

    return process.stdout.strip()


def extract_json(text: str) -> Optional[dict]:
    """
    Intenta extraer un objeto JSON { ... } de un texto,
    por si el modelo añade texto antes o después.
    """
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        fragment = text[start:end+1]
        try:
            return json.loads(fragment)
        except Exception as e:
            print("Error parseando JSON:", e)
            return None
    return None


def send_mqtt_led(action: str) -> bool:
    """
    Envía un comando de LED simple al ESP32 vía MQTT.
    action: 'LED_ON' o 'LED_OFF'
    Publica en el topic MQTT_TOPIC_LED con payload 'ON' o 'OFF'.
    """
    if not mqtt_connected:
        return False
    try:
        if action == "LED_ON":
            result = mqtt_client.publish(MQTT_TOPIC_LED, "ON")
        elif action == "LED_OFF":
            result = mqtt_client.publish(MQTT_TOPIC_LED, "OFF")
        else:
            return False

        # result[0] es el código de estado de paho-mqtt (0 = OK)
        return result[0] == 0
    except Exception as e:
        print("MQTT ERROR (LED):", e)
        return False


def send_mqtt_rgb(action: str) -> bool:
    """
    Envía un comando de estado de ánimo al RGB vía MQTT.
    action:
      - 'RGB_ALEGRE'  -> payload 'HAPPY'
      - 'RGB_TRISTE'  -> payload 'SAD'
      - 'RGB_NEUTRAL' -> payload 'NEUTRAL' (apagar o color neutro)
    """
    if not mqtt_connected:
        return False
    try:
        payload = None
        if action == "RGB_ALEGRE":
            payload = "HAPPY"
        elif action == "RGB_TRISTE":
            payload = "SAD"
        elif action == "RGB_NEUTRAL":
            payload = "NEUTRAL"

        if payload is None:
            return False

        result = mqtt_client.publish(MQTT_TOPIC_RGB, payload)
        return result[0] == 0
    except Exception as e:
        print("MQTT ERROR (RGB):", e)
        return False


@app.post("/voice-intent")
async def voice_intent(audio: UploadFile = File(...)):
    # Ruta donde se guardarán los audios
    save_dir = AUDIO_SAVE_DIR
    os.makedirs(save_dir, exist_ok=True)

    # Crear nombre único con fecha y hora
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}_{audio.filename}"
    file_path = os.path.join(save_dir, filename)

    # Leer y guardar el contenido
    content = await audio.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Archivo vacío")

    max_bytes = MAX_AUDIO_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Archivo supera {MAX_AUDIO_MB} MB")

    with open(file_path, "wb") as f:
        f.write(content)

    # Detectar tipo de contenido (por si algún día llega algo que no es audio)
    content_type = audio.content_type or ""
    es_audio = content_type.startswith("audio/")

    # --- Transcribir audio con Whisper ---
    texto_transcrito = ""
    t0 = time.time()
    if es_audio:
        try:
            result = transcribe(whisper_model, file_path)
            texto_transcrito = result.get("text", "").strip()
        except Exception as e:
            print("Error Whisper:", e)
            texto_transcrito = ""
    else:
        print(f"Archivo no es audio (content_type={content_type}), se omite Whisper.")
        texto_transcrito = ""
    t1 = time.time()

    # --- Llamada a Qwen2 con el texto transcrito ---
    prompt = textwrap.dedent(f"""
        Eres un sistema de análisis de intenciones a partir de texto y detección de estado de ánimo.

        El usuario dijo (transcripción del audio):
        "{texto_transcrito}"

        Tu tarea es:
        1. Entender qué quiere el usuario.
        2. Detectar si el usuario expresa cómo se siente (por ejemplo: "me siento alegre", "estoy triste").
        3. Devolver solo un JSON válido, sin nada de texto adicional.
        4. Usar exactamente la siguiente estructura:

        {{
          "texto": "texto transcrito del usuario",
          "intencion": "intención principal en pocas palabras",
          "detalle": "explicación breve de lo que el usuario quiere o pregunta",
          "siguiente_paso_led": "encender_led, apagar_led o ninguna_accion",
          "estado_animo": "alegre, triste, neutral o desconocido",
          "siguiente_paso_rgb": "rgb_alegre, rgb_triste, rgb_neutral o ninguna_accion"
        }}

        Reglas importantes:
        - Responde SOLO con el objeto JSON.
        - No añadas explicaciones fuera del JSON.
        - No uses Markdown ni comentarios.
        - Copia el texto transcrito en el campo "texto".
        - El lenguaje del usuario es español, no italiano.

        Para el campo "siguiente_paso_led":
        - Si el usuario dice algo como "prende led", "enciende el led", "prende la luz",
          usa exactamente "encender_led".
        - Si el usuario dice algo como "apaga led", "apaga la luz",
          usa exactamente "apagar_led".
        - Si no está claro qué acción tomar sobre el LED, usa exactamente "ninguna_accion".

        Para el estado de ánimo y el RGB:
        - Si el usuario dice que se siente alegre, feliz, contento o similar:
          - "estado_animo": "alegre"
          - "siguiente_paso_rgb": "rgb_alegre"
        - Si el usuario dice que se siente triste, deprimido, desanimado o similar:
          - "estado_animo": "triste"
          - "siguiente_paso_rgb": "rgb_triste"
        - Si el usuario no menciona claramente cómo se siente:
          - "estado_animo": "neutral" o "desconocido"
          - "siguiente_paso_rgb": "rgb_neutral" o "ninguna_accion" según lo veas más apropiado.
    """)

    ia_raw = call_ollama_qwen2(prompt)
    ia_json = extract_json(ia_raw)

    # --- Enviar comando por MQTT según la intención ---
    accion_mqtt_led = None
    accion_mqtt_rgb = None

    if ia_json:
        # LED simple
        sp_led = ia_json.get("siguiente_paso_led", ia_json.get("siguiente_paso", ""))
        if sp_led == "encender_led":
            ok = send_mqtt_led("LED_ON")
            accion_mqtt_led = "LED_ON_OK" if ok else "LED_ON_ERROR"
        elif sp_led == "apagar_led":
            ok = send_mqtt_led("LED_OFF")
            accion_mqtt_led = "LED_OFF_OK" if ok else "LED_OFF_ERROR"
        else:
            accion_mqtt_led = "SIN_ACCION_LED"

        # RGB estado de ánimo
        sp_rgb = ia_json.get("siguiente_paso_rgb", "")
        if sp_rgb == "rgb_alegre":
            ok = send_mqtt_rgb("RGB_ALEGRE")
            accion_mqtt_rgb = "RGB_ALEGRE_OK" if ok else "RGB_ALEGRE_ERROR"
        elif sp_rgb == "rgb_triste":
            ok = send_mqtt_rgb("RGB_TRISTE")
            accion_mqtt_rgb = "RGB_TRISTE_OK" if ok else "RGB_TRISTE_ERROR"
        elif sp_rgb == "rgb_neutral":
            ok = send_mqtt_rgb("RGB_NEUTRAL")
            accion_mqtt_rgb = "RGB_NEUTRAL_OK" if ok else "RGB_NEUTRAL_ERROR"
        else:
            accion_mqtt_rgb = "SIN_ACCION_RGB"
    else:
        accion_mqtt_led = "SIN_JSON"
        accion_mqtt_rgb = "SIN_JSON"

    return {
        "ok": True,
        "filename": filename,
        "saved_path": file_path,
        "content_type": content_type,
        "texto_transcrito": texto_transcrito,
        "ia_raw": ia_raw,       # respuesta completa del modelo
        "ia_json": ia_json,     # JSON parseado (o null si algo falla)
        "accion_mqtt_led": accion_mqtt_led,
        "accion_mqtt_rgb": accion_mqtt_rgb,
        "mqtt_connected": mqtt_connected,
        "latencia_whisper_seg": round(t1 - t0, 3),
    }
