🧠 Proyecto IA + IoT

Control por voz → Qwen2 7B → MQTT → ESP32 + LED/RGB

Este proyecto integra un sistema de inteligencia artificial local (Qwen2 7B Q4), controlado por voz desde Android, donde cada intención se convierte en comandos MQTT que se ejecutan físicamente en un ESP32.
Permite prender/apagar luces y cambiar colores RGB según el estado de ánimo del usuario.

🚀 Tecnologías utilizadas
Componente	Tecnología
IA local	Qwen2 7B Instruct Q4 (Ollama)
Backend	FastAPI + Uvicorn
Audio → Texto	Whisper Timestamped
Mensajería IoT	MQTT (Mosquitto)
Microcontrolador	ESP32 Devkit V1
Frontend	HTML + JS
Hosting local	Ubuntu Server 22.04
Protocolo físico	GPIO LED / RGB
📂 Estructura del Repositorio
proyecto1/
│
├── frontend/
│   └── index.html
│
├── backend/
│   └── app_api.py
│
├── esp32/
│   └── arduino_esp32.ino
│
└── README.md

🏗 Ubicación Real en el Servidor (Ubuntu Server)
🟦 Frontend

Archivo en GitHub:
frontend/index.html

Ruta real en tu servidor:

/var/www/html/index.html


Se accede desde cualquier navegador:

http://TU_IP_DEL_SERVIDOR/

🟦 Backend – API FastAPI

Archivo en GitHub:
backend/app_api.py

Ruta real en tu servidor (CORREGIDA):

/root/app_api.py


📌 Esto sucede porque lo ejecutas como superusuario (root).

Comando para ejecutarlo:
cd /root
uvicorn app_api:app --host 0.0.0.0 --port 80

🟦 Firmware ESP32

Archivo en GitHub:
esp32/arduino_esp32.ino

Este archivo se compila y sube al ESP32 usando Arduino IDE.
Aquí se manejan las suscripciones MQTT y el control del LED y RGB.

🔄 Flujo Completo del Sistema
ANDROID → graba audio  
       → se envía a FASTAPI
       → Whisper convierte voz → texto
       → Qwen2 7B interpreta la intención
       → API genera JSON con la acción
       → Broker MQTT recibe el comando
       → ESP32 ejecuta la acción física
       → LED / RGB responde según emoción

⚙ Configuración del Backend (FastAPI)
1. Crear entorno e instalar dependencias
sudo apt update
pip install fastapi uvicorn paho-mqtt whisper-timestamped

2. Ejecutar la API
cd /root
uvicorn app_api:app --host 0.0.0.0 --port 80

🤖 Modelo de IA (Ollama)
Ver modelos instalados
ollama list

Instalar Qwen2 7B Q4
ollama pull qwen2:7b-q4

📡 MQTT – Topics del Proyecto
Acción	Topic	Payload
Encender / apagar LED	casa/esp32/led	ON, OFF
Emoción → color RGB	casa/esp32/rgb	{"color": "blue"}

Ejemplo manual:

mosquitto_pub -h 192.168.0.12 -t casa/esp32/led -m ON

🔥 Lógica de Emociones (RGB)
Emoción detectada	Color enviado	Color RGB
Alegre	yellow	🟨 Amarillo
Triste	blue	🔵 Azul
Molesto	red	🔴 Rojo
Neutral	white	⚪ Blanco
🧪 Test rápido
1. Probar MQTT
mosquitto_sub -h 192.168.0.12 -t "#"

2. Probar LED manual
mosquitto_pub -h 192.168.0.12 -t casa/esp32/led -m ON

3. Probar RGB manual
mosquitto_pub -h 192.168.0.12 -t casa/esp32/rgb -m '{"color":"blue"}'

📱 Flujo desde Android

El usuario graba un audio

El frontend envía el archivo a /voice-intent

FastAPI lo guarda → Whisper lo transcribe

Qwen2 7B analiza intención

API genera el mensaje MQTT correcto

ESP32 actúa físicamente

🧩 Próximas mejoras

Integración con Shelly Pro 4PM

Dashboard UI en tiempo real

Control de sensores (MQ-2, DS18B20, DHT22)

Niveles de acceso para otros usuarios

Implementación de MQTT Secure (TLS)

👑 Autor

Abraham
Proyecto IoT + IA – Control por voz con Qwen2 7B, FastAPI y ESP32
Perú 🇵🇪
