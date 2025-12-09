#include <WiFi.h>
#include <PubSubClient.h>

const char* ssid = "abraham-2.4";
const char* password = "Tecsup2024";

// Debe coincidir con la IP/host configurada en el backend FastAPI (MQTT_SERVER)
const char* mqtt_server = "192.168.0.12";  // Broker MQTT

// Topics alineados con los valores por defecto del backend (MQTT_TOPIC_LED/MQTT_TOPIC_RGB)
const char* TOPIC_LED = "casa/esp32/led";
const char* TOPIC_RGB = "casa/esp32/rgb";

WiFiClient espClient;
PubSubClient client(espClient);

// LED simple (puedes dejar el GPIO2 si te funciona bien)
const int LED_PIN = 2;

// Pines del módulo RGB (common cathode: pin "-" a GND)
const int R_PIN = 5;   // D5
const int G_PIN = 18;  // D18
const int B_PIN = 19;  // D19

void setRGB(bool r, bool g, bool b) {
  digitalWrite(R_PIN, r ? HIGH : LOW);
  digitalWrite(G_PIN, g ? HIGH : LOW);
  digitalWrite(B_PIN, b ? HIGH : LOW);
}

void setMoodColor(const String &mood) {
  // Payload esperado: HAPPY, SAD o NEUTRAL (en mayúsculas)
  if (mood == "HAPPY") {
    // Amarillo (rojo + verde)
    setRGB(true, true, false);
  } else if (mood == "SAD") {
    // Azul
    setRGB(false, false, true);
  } else {
    // NEUTRAL u otra cosa => apagar
    setRGB(false, false, false);
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (int i = 0; i < length; i++) msg += (char)payload[i];
  msg.trim();
  msg.toUpperCase();

  String top = String(topic);

  Serial.print("MSG [");
  Serial.print(top);
  Serial.print("]: ");
  Serial.println(msg);

  // ----- Control LED simple -----
  if (top == TOPIC_LED) {
    if (msg == "ON") {
      digitalWrite(LED_PIN, HIGH);
    } else if (msg == "OFF") {
      digitalWrite(LED_PIN, LOW);
    }
  }

  // ----- Control RGB por estado de ánimo -----
  else if (top == TOPIC_RGB) {
    setMoodColor(msg);
  }
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Intentando conectar MQTT...");
    if (client.connect("ESP32Client")) {
      Serial.println("conectado.");
      client.subscribe(TOPIC_LED);
      client.subscribe(TOPIC_RGB);
      Serial.print("Suscrito a LED en: ");
      Serial.println(TOPIC_LED);
      Serial.print("Suscrito a RGB en: ");
      Serial.println(TOPIC_RGB);
    } else {
      Serial.print("falló, rc=");
      Serial.print(client.state());
      Serial.println(" intentando de nuevo en 5s");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(LED_PIN, OUTPUT);
  pinMode(R_PIN, OUTPUT);
  pinMode(G_PIN, OUTPUT);
  pinMode(B_PIN, OUTPUT);

  // Apagar todo al inicio
  digitalWrite(LED_PIN, LOW);
  setRGB(false, false, false);

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi conectado.");

frontend/index.html

