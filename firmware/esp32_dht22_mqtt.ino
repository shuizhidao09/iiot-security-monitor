#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include "device_settings.h"

// Wiring:
// DHT22 VCC -> 3.3V
// DHT22 GND -> GND
// DHT22 DATA -> GPIO14

DHT dht(DHTPIN, DHTTYPE);
WiFiClient espClient;
PubSubClient mqttClient(espClient);

char telemetryTopic[96];
char statusTopic[96];
char payload[256];

unsigned long lastPublish = 0;
unsigned long lastWiFiRetry = 0;
unsigned long lastMQTTRetry = 0;
unsigned long seqNo = 0;

bool connectWiFi();
bool connectMQTT();
void publishSensorData();

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
  Serial.println("ESP32 DHT22 MQTT start");

  dht.begin();

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE_ID);

  snprintf(telemetryTopic, sizeof(telemetryTopic), "%s/%s/telemetry", MQTT_BASE_TOPIC, DEVICE_ID);
  snprintf(statusTopic, sizeof(statusTopic), "%s/%s/status", MQTT_BASE_TOPIC, DEVICE_ID);

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setKeepAlive(30);
  mqttClient.setBufferSize(256);

  connectWiFi();
  connectMQTT();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED && millis() - lastWiFiRetry >= WIFI_RETRY_INTERVAL_MS) {
    lastWiFiRetry = millis();
    connectWiFi();
  }

  if (WiFi.status() == WL_CONNECTED && !mqttClient.connected() && millis() - lastMQTTRetry >= MQTT_RETRY_INTERVAL_MS) {
    lastMQTTRetry = millis();
    connectMQTT();
  }

  if (mqttClient.connected()) {
    mqttClient.loop();
  }

  if (millis() - lastPublish >= PUBLISH_INTERVAL_MS) {
    lastPublish = millis();
    publishSensorData();
  }
}

bool connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  Serial.printf("Connecting to WiFi: %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_CONNECT_TIMEOUT_MS) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print("WiFi connected, IP: ");
    Serial.println(WiFi.localIP());
    return true;
  }

  Serial.println();
  Serial.println("WiFi connect failed");
  return false;
}

bool connectMQTT() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Skip MQTT: WiFi not connected");
    return false;
  }

  if (mqttClient.connected()) {
    return true;
  }

  Serial.print("Connecting to MQTT...");

  bool ok = false;
  if (strlen(MQTT_USERNAME) > 0) {
    ok = mqttClient.connect(
      MQTT_CLIENT_ID,
      MQTT_USERNAME,
      MQTT_PASSWORD,
      statusTopic,
      0,
      true,
      "offline"
    );
  } else {
    ok = mqttClient.connect(
      MQTT_CLIENT_ID,
      statusTopic,
      0,
      true,
      "offline"
    );
  }

  if (ok) {
    Serial.println(" connected");
    mqttClient.publish(statusTopic, "online", true);
    return true;
  }

  Serial.print(" failed, rc=");
  Serial.println(mqttClient.state());
  return false;
}

void publishSensorData() {
  float humidity = dht.readHumidity();
  float temperature = dht.readTemperature();

  if (isnan(humidity) || isnan(temperature)) {
    Serial.println("Failed to read from DHT22");
    return;
  }

  seqNo++;

  int rssi = (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : 0;
  snprintf(payload, sizeof(payload),
           "{\"deviceId\":\"%s\",\"seq\":%lu,\"temperature\":%.2f,\"humidity\":%.2f,\"rssi\":%d,\"uptimeMs\":%lu}",
           DEVICE_ID, seqNo, temperature, humidity, rssi, millis());

  Serial.print("Publish: ");
  Serial.println(payload);

  if (!mqttClient.connected()) {
    Serial.println("MQTT not connected, skip publish");
    return;
  }

  if (!mqttClient.publish(telemetryTopic, payload)) {
    Serial.println("MQTT publish failed");
  }
}
