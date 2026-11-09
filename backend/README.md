# Python Backend Run Guide

This backend subscribes to the MQTT topic `iiot/device/+/telemetry` published by ESP32 devices and provides the Vue dashboard with:

- `GET /api/health`
- `POST /api/auth/login`
- `GET /api/dashboard`
- `POST /api/telemetry`
- `GET /api/telemetry/history`
- `WebSocket /ws`

The dashboard and telemetry history endpoints require a bearer token from the login endpoint. The administrator username and password are read only from `ADMIN_USERNAME` and `ADMIN_PASSWORD`; there is no built-in demo account. The backend refuses to start if either variable is missing or empty. A successful login returns an expiring in-memory session token. The Vue application stores that token in the browser and sends it with REST requests and the WebSocket query string. The history endpoint accepts `startDate`, `endDate`, `deviceId`, and `limit` query parameters.

With MySQL enabled and available, every accepted telemetry message is written to `telemetry_snapshots`. Both `telemetry_snapshots` and `alerts` are created automatically when the backend starts. The newest persisted alerts are restored on startup. Alerts are deduplicated within `ALERT_DEDUPE_WINDOW_MS` (default 30 seconds) and persisted with `first_seen_ms`, `last_seen_ms`, and `occurrence_count`; repeated alerts update the latter two fields. If an alert's first insertion failed, a later merge recreates its row with the full accumulated count. Suspicious sequence messages, malformed payloads, and device ID mismatches are discarded before device state, in-memory telemetry history, or telemetry persistence is changed; only their alerts are updated.

The MQTT payload must contain a nonempty string `deviceId`, and it must exactly match the ID in the topic (`iiot/device/<deviceId>/telemetry`). The backend never fills a missing payload ID from the topic. Both `seq` and `uptimeMs` are required non-negative JSON integers; missing values, strings, booleans, and fractions are rejected. Sequence numbers must increase for a device, but gaps are allowed. A restart is inferred only when `seq` strictly decreases to at most `SEQ_RESTART_MAX` (default 3) and `uptimeMs` decreases by at least `SEQ_RESTART_MIN_UPTIME_DROP_MS` (default 5000 ms). Duplicate sequences, smaller uptime rollbacks, and other counter inconsistencies are discarded. This is a counter-based restart heuristic, not proof of a device's identity. Device sequence state is held in memory and starts fresh after a backend restart. Alert levels are limited to `info`, `low`, `medium`, and `high`; connection/recovery/restart events use `info`.

Each WebSocket message includes a top-level `backendReceivedAtMs` Unix millisecond timestamp. For telemetry and rejection alerts, this is captured at the MQTT callback or manual HTTP handler entry, before validation, database writes, and broadcast scheduling. The initial snapshot uses the WebSocket connection time; periodic/status snapshots use their generation time. The frontend store exposes `lastBackendReceivedAtMs` and `lastWebSocketLatencyMs = Date.now() - backendReceivedAtMs`. Backend and browser clocks must be synchronized for this estimate; a negative value indicates clock skew. It measures backend receipt to browser delivery, not device publish latency.

Set the MySQL connection before starting the backend. PowerShell example:

```powershell
$env:MYSQL_ENABLED = "true"
$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_PORT = "3306"
$env:MYSQL_USER = "root"
$env:MYSQL_PASSWORD = "your-password"
$env:MYSQL_DATABASE = "iiot_monitor"
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "your-admin-password"
$env:FRONTEND_ORIGIN = "http://localhost:5173"
# Optional: maximum sequence accepted after a device restart, default 3
$env:SEQ_RESTART_MAX = "3"
# Optional: minimum uptime decrease required for a restart, default 5000 ms
$env:SEQ_RESTART_MIN_UPTIME_DROP_MS = "5000"
# Optional: session lifetime in milliseconds, default 8 hours
$env:AUTH_SESSION_TTL_MS = "28800000"
```

| Environment variable | Required / default | Purpose |
| --- | --- | --- |
| `ADMIN_USERNAME` | Required | Administrator login name, with no built-in fallback. |
| `ADMIN_PASSWORD` | Required | Administrator login password, with no built-in fallback. |
| `MYSQL_PASSWORD` | Required when `MYSQL_ENABLED=true` | MySQL password; missing or empty values prevent database connection. |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | One exact allowed HTTP(S) origin, including scheme and port, without a path or wildcard. Set it to the actual browser address; `localhost` and `127.0.0.1` are different origins. |
| `SEQ_RESTART_MAX` | `3` | Highest sequence number eligible for restart detection. |
| `SEQ_RESTART_MIN_UPTIME_DROP_MS` | `5000` | Minimum uptime rollback for restart detection; must be positive. |
| `AUTH_SESSION_TTL_MS` | `28800000` | Login session lifetime in milliseconds. |

`MYSQL_ENABLED=false` disables persistence and does not require a MySQL password. Environment variables must be present in the process launching the backend (or its PyCharm run configuration); this backend does not load a `.env` file automatically.

From the `backend` directory, initialize the configured database and both tables after setting the environment variables:

```powershell
python init_mysql.py
```

The initializer uses `CREATE DATABASE IF NOT EXISTS` and the same automatic table creation as the backend. Existing databases, tables, and data are preserved. The MySQL account needs permission to create the database/tables. Its password is read from `MYSQL_PASSWORD` and is never stored in the script.

Alternatively, create the database manually:

```sql
CREATE DATABASE iiot_monitor CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

The backend keeps serving realtime data if MySQL is unavailable or its password is missing, but logs the connection/configuration error and reports `mysqlConnected: false` in `/api/health` and dashboard snapshots. The next telemetry or alert write retries the connection. Configure credentials and restart the backend after changing environment variables. Events that never get a successful database write remain in memory only.

## Run In PyCharm

1. Open the project root directory in PyCharm.
2. Enter the `backend` directory.
3. Configure the Python interpreter for the project.
4. Run the following commands in the PyCharm terminal:

```powershell
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

After the backend starts, visit:

```text
http://127.0.0.1:8000/api/health
```

The frontend is still available at:

```text
http://localhost:5173/
```
