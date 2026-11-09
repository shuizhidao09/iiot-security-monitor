# IIoT Security Monitor

Source code for the bachelor's thesis *Design and Implementation of a Lightweight Cybersecurity Monitoring System for Industrial IoT Devices: A Rule-based Approach Using ESP32 and MQTT* (Jie Xu, HAMK, 2026).

The system collects temperature and humidity data with an ESP32 and a DHT22 sensor, sends it over MQTT to a FastAPI backend, detects anomalies with predefined rules, stores accepted telemetry and alerts in MySQL and shows them on a Vue 3 dashboard updated through WebSocket.

This is a laboratory prototype. It is not intended for production use: the evaluated MQTT setup used no TLS, no broker authentication and no topic access control.

## Repository structure

| Folder | Content |
| --- | --- |
| `firmware/` | ESP32 firmware (Arduino). Copy `device_settings.example.h` to `device_settings.h` and fill in your own Wi-Fi and MQTT broker settings. |
| `backend/` | FastAPI backend: MQTT subscription, message validation, rule-based anomaly detection, alert de-duplication, MySQL persistence, REST API and WebSocket. See `backend/README.md` for configuration. |
| `frontend/` | Vue 3 dashboard (Vite, Pinia, Element Plus, ECharts) with login, real-time dashboard and history page. |

## Quick start

1. **Broker**: run an MQTT broker, for example Mosquitto on port 1883.
2. **Firmware**: open `firmware/esp32_dht22_mqtt.ino` in the Arduino IDE, create `device_settings.h` from the example file and upload it to the ESP32. Required libraries: PubSubClient and DHT sensor library.
3. **Backend**: in `backend/`, set the environment variables described in `backend/README.md` (at least `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `MYSQL_PASSWORD` and `MQTT_HOST`), then run:

   ```bash
   pip install -r requirements.txt
   python -m uvicorn main:app --host 0.0.0.0 --port 8000
   ```

4. **Frontend**: in `frontend/`, run:

   ```bash
   npm install
   npm run dev
   ```

   Open http://localhost:5173 and log in with the administrator account.

## Main configuration values

| Setting | Default | Meaning |
| --- | --- | --- |
| Reporting interval | 5 s | ESP32 publishing interval |
| `OFFLINE_THRESHOLD_MS` | 15000 | Device offline threshold |
| `TEMP_ALERT_THRESHOLD` | 31 °C | Temperature alert threshold |
| `HUMIDITY_ALERT_THRESHOLD` | 65 % | Humidity alert threshold |
| `ALERT_DEDUPE_WINDOW_MS` | 30000 | Alert de-duplication window |

The temperature and humidity thresholds are also defined in `frontend/src/stores/monitor.js` for the threshold lines of the trend chart and must be changed in both places.
