# app_api.py — Guarda audios, transcribe con Whisper,
# analiza intención con Qwen2 7B Instruct Q4 (Ollama)
# y envía comandos a un ESP32 usando MQTT (LED + RGB estado de ánimo).

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import os
import subprocess
import json
import textwrap
import requests

# --- Whisper ---
from whisper_timestamped import load_model, transcribe

# --- MQTT ---
import paho.mqtt.client as mqtt

# ===== FUNCIÓN TTS (Texto a voz con espeak-ng) =====
def speak_text(text: str):
    """
    Convierte texto a voz usando espeak-ng y lo reproduce por el altavoz del servidor.
    Requiere tener instalado en Ubuntu:
      sudo apt install espeak-ng alsa-utils
    """
    if not text:
        return

    text = text.strip()
    if len(text) > 300:
        text = text[:300] + " ..."

    # Voz español latino (-v es-la). Puedes cambiar el texto cuando quieras.
    cmd = f'espeak-ng -v es-la "{text}" --stdout | aplay'
    try:
        subprocess.run(cmd, shell=True, check=True)
    except Exception as e:
        print("[TTS] Error al reproducir voz:", e)


# ===== CONFIGURACIÓN MQTT =====
MQTT_SERVER = "192.168.0.63"          # IP de tu broker (Ubuntu)
MQTT_PORT = 1883
MQTT_TOPIC_LED = "casa/esp32/led"     # Topic para LED simple
MQTT_TOPIC_RGB = "casa/esp32/rgb"     # Topic para RGB (emociones)

# Crear cliente MQTT global
mqtt_client = mqtt.Client()
try:
    print("Intentando conectar a MQTT...")
    mqtt_client.connect(MQTT_SERVER, MQTT_PORT, 60)
    mqtt_client.loop_start()  # <<< IMPORTANTE: inicia el hilo de red
    print(f"Conectado a MQTT en {MQTT_SERVER}:{MQTT_PORT}")
except Exception as e:
    print("ERROR: No se pudo conectar al broker MQTT:", e)

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
    return {"pong": True}


# Nombre del modelo Ollama (pon aquí el que TÚ quieras usar)
OLLAMA_MODEL = "qwen2:1.5b-instruct"

def call_ollama_qwen2(prompt: str) -> str:
    """
    Envía el prompt a Ollama usando la API HTTP.
    Mucho más rápido que lanzar 'ollama run' con subprocess.
    """
    try:
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,  # para que devuelva todo junto
        }
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        # En la API de Ollama, el texto viene normalmente en 'response'
        return data.get("response", "").strip()
    except Exception as e:
        print("Error llamando a Ollama vía HTTP:", e)
        return ""

def extract_json(text: str):
    """
    Intenta extraer un objeto JSON { ... } de un texto,
    por si el modelo añade texto antes o después.
    """
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
    save_dir = "/home/abraham/audios_recibidos"
    os.makedirs(save_dir, exist_ok=True)

    # Crear nombre único con fecha y hora
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}_{audio.filename}"
    file_path = os.path.join(save_dir, filename)

    # Leer y guardar el contenido
    with open(file_path, "wb") as f:
        content = await audio.read()
        f.write(content)

    # Detectar tipo de contenido (por si algún día llega algo que no es audio)
    content_type = audio.content_type or ""
    es_audio = content_type.startswith("audio/")

    # --- Transcribir audio con Whisper ---
    texto_transcrito = ""
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

    # --- Confirmación por voz según las acciones ejecutadas ---

    try:
        # Caso 1: LED encendido
        if accion_mqtt_led == "LED_ON_OK":
            speak_text("Estoy prendiendo las luces de acuerdo a su ánimo el día de hoy.")

        # Caso 2: LED apagado
        elif accion_mqtt_led == "LED_OFF_OK":
            speak_text("Estoy apagando las luces.")

        # Caso 3: CUALQUIER acción RGB correcta
        elif accion_mqtt_rgb in ("RGB_ALEGRE_OK"):
            speak_text("Estoy prendiendo las luces de acuerdo a su ánimo el día de hoy.")

        elif accion_mqtt_rgb in ("RGB_TRISTE_OK"):
            speak_text("Luces prendidas en modo tristeza.")

        elif accion_mqtt_rgb in ("RGB_NEUTRAL_OK"):
            speak_text("Estoy apagando las luces.")

    except Exception as e:
        print("[TTS] Error en confirmación de voz:", e)



    return {
        "ok": True,
        "filename": filename,
        "saved_path": file_path,
        "content_type": content_type,
        "texto_transcrito": texto_transcrito,
        "ia_raw": ia_raw,       # respuesta completa del modelo
        "ia_json": ia_json,     # JSON parseado (o null si algo falla)
        "accion_mqtt_led": accion_mqtt_led,
        "accion_mqtt_rgb": accion_mqtt_rgb
    }
