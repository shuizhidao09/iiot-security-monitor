#ifndef DEVICE_SETTINGS_H
#define DEVICE_SETTINGS_H

// Copy this file to device_settings.h and replace the placeholder values
// with your own settings. Do not commit device_settings.h to version control.

// ===== WiFi Settings =====
#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"

// ===== MQTT Settings =====
// Replace with your own broker IP if you use a local Mosquitto/EMQX server.
#define MQTT_BROKER     "YOUR_BROKER_IP"
#define MQTT_PORT       1883
#define MQTT_USERNAME   ""   // leave empty for anonymous connection
#define MQTT_PASSWORD   ""

// ===== Device Settings =====
#define DEVICE_ID       "esp32_003"
#define MQTT_CLIENT_ID  DEVICE_ID
#define MQTT_BASE_TOPIC "iiot/device"

// ===== Sensor Pin =====
#define DHTPIN 14
#define DHTTYPE DHT22

// ===== Timing =====
#define WIFI_CONNECT_TIMEOUT_MS 15000
#define WIFI_RETRY_INTERVAL_MS  10000
#define MQTT_RETRY_INTERVAL_MS  10000
#define PUBLISH_INTERVAL_MS     5000

#endif
