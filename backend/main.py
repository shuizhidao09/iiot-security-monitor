import asyncio
import json
import math
import os
import random
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

import paho.mqtt.client as mqtt
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from database import DatabaseUnavailableError, MySQLSnapshotStore


HTTP_PORT = int(os.getenv("PORT", "8000"))
MQTT_HOST = os.getenv("MQTT_HOST", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "iiot/device/+/telemetry")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

OFFLINE_THRESHOLD_MS = int(os.getenv("OFFLINE_THRESHOLD_MS", "15000"))
TEMP_ALERT_THRESHOLD = float(os.getenv("TEMP_ALERT_THRESHOLD", "31"))
HUMIDITY_ALERT_THRESHOLD = float(os.getenv("HUMIDITY_ALERT_THRESHOLD", "65"))
ALERT_DEDUPE_WINDOW_MS = int(os.getenv("ALERT_DEDUPE_WINDOW_MS", "30000"))
SEQ_RESTART_MAX = int(os.getenv("SEQ_RESTART_MAX", "3"))
SEQ_RESTART_MIN_UPTIME_DROP_MS = int(os.getenv("SEQ_RESTART_MIN_UPTIME_DROP_MS", "5000"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "80"))
ALERT_LIMIT = int(os.getenv("ALERT_LIMIT", "50"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").strip().rstrip("/")
AUTH_SESSION_TTL_MS = int(os.getenv("AUTH_SESSION_TTL_MS", str(8 * 60 * 60 * 1000)))

ALERT_LEVELS = {"info", "low", "medium", "high"}
_DEVICE_TOPIC_RE = re.compile(r"(?:^|/)device/([^/]+)/telemetry$")


state_lock = Lock()
app_loop: asyncio.AbstractEventLoop | None = None
mqtt_client: mqtt.Client | None = None
offline_task: asyncio.Task | None = None
mysql_store = MySQLSnapshotStore()
auth_scheme = HTTPBearer(auto_error=False)
auth_lock = Lock()
auth_sessions: dict[str, int] = {}

state: dict[str, Any] = {
    "broker": f"{MQTT_HOST}:{MQTT_PORT}",
    "mqttConnected": False,
    "mysqlConnected": False,
    "devices": {},
    "alerts": [],
    "telemetryHistory": [],
}


class LoginRequest(BaseModel):
    username: str
    password: str


def validate_runtime_config() -> None:
    missing = [name for name, value in (("ADMIN_USERNAME", ADMIN_USERNAME), ("ADMIN_PASSWORD", ADMIN_PASSWORD)) if not value]
    if missing:
        raise RuntimeError(f"Required environment variables are missing: {', '.join(missing)}")
    origin = urlsplit(FRONTEND_ORIGIN)
    if (
        origin.scheme not in {"http", "https"}
        or not origin.hostname
        or "*" in FRONTEND_ORIGIN
        or origin.username is not None
        or origin.password is not None
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise RuntimeError("FRONTEND_ORIGIN must be one HTTP(S) origin, for example http://localhost:5173")
    if SEQ_RESTART_MAX < 0 or SEQ_RESTART_MIN_UPTIME_DROP_MS <= 0:
        raise RuntimeError("SEQ_RESTART_MAX must be non-negative and SEQ_RESTART_MIN_UPTIME_DROP_MS must be positive")


class TelemetryRejectedError(ValueError):
    """A telemetry message that must be discarded before state persistence."""

    def __init__(
        self,
        message: str,
        *,
        device_id: str = "unknown",
        alert_type: str = "format",
        title: str = "Invalid Data Format",
        level: str = "medium",
    ) -> None:
        super().__init__(message)
        self.device_id = device_id or "unknown"
        self.alert_type = alert_type
        self.title = title
        self.level = level if level in ALERT_LEVELS else "medium"


def create_auth_session() -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    expires_at = now_ms() + AUTH_SESSION_TTL_MS
    with auth_lock:
        current = now_ms()
        expired = [session for session, expiry in auth_sessions.items() if expiry <= current]
        for session in expired:
            del auth_sessions[session]
        auth_sessions[token] = expires_at
    return token, expires_at


def is_valid_auth_token(token: str | None) -> bool:
    if not token:
        return False
    with auth_lock:
        expires_at = auth_sessions.get(token)
        if expires_at is None:
            return False
        if expires_at <= now_ms():
            del auth_sessions[token]
            return False
        return True


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
) -> str:
    token = credentials.credentials if credentials else None
    if not is_valid_auth_token(token):
        raise HTTPException(status_code=401, detail="Authentication required")
    return token


def now_ms() -> int:
    return int(time.time() * 1000)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


def format_datetime(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def reason_code_value(reason_code: Any) -> int:
    try:
        return int(reason_code)
    except (TypeError, ValueError):
        return int(getattr(reason_code, "value", -1))


def create_alert_locked(
    level: str,
    title: str,
    device_id: str,
    description: str,
    alert_type: str,
) -> dict[str, Any]:
    if level not in ALERT_LEVELS:
        level = "medium"
    timestamp = now_ms()
    for index, alert in enumerate(state["alerts"]):
        is_same_alert = (
            alert.get("type") == alert_type
            and alert.get("deviceId") == device_id
            and alert.get("title") == title
            and timestamp - int(alert.get("lastSeenMs", alert.get("timestamp", 0))) < ALERT_DEDUPE_WINDOW_MS
        )
        if is_same_alert:
            alert["level"] = level
            alert["description"] = description
            alert["timestamp"] = timestamp
            alert["lastSeenMs"] = timestamp
            alert["occurrenceCount"] = int(alert.get("occurrenceCount", 1)) + 1
            mysql_store.save_alert(alert, merged=True)
            state["mysqlConnected"] = mysql_store.connected
            state["alerts"].insert(0, state["alerts"].pop(index))
            return alert

    alert = {
        "id": f"ALT-{timestamp}-{secrets.token_hex(8)}",
        "level": level,
        "title": title,
        "deviceId": device_id,
        "description": description,
        "type": alert_type,
        "timestamp": timestamp,
        "firstSeenMs": timestamp,
        "lastSeenMs": timestamp,
        "occurrenceCount": 1,
    }
    state["alerts"].insert(0, alert)
    del state["alerts"][ALERT_LIMIT:]
    mysql_store.save_alert(alert, merged=False)
    state["mysqlConnected"] = mysql_store.connected
    return alert


def topic_device_id(topic: str) -> str | None:
    match = _DEVICE_TOPIC_RE.search(topic.strip())
    return match.group(1) if match else None


def _require_counter(value: Any, field_name: str) -> int:
    # bool is an int subclass; accepting it or truncating floats would let
    # malformed counters pass sequence/restart validation.
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError(f"{field_name} must be a non-negative integer (at most 2^63 - 1)")
    return value


def normalize_telemetry(raw_payload: str, topic: str, *, received_at_ms: int | None = None) -> dict[str, Any]:
    timestamp = now_ms() if received_at_ms is None else received_at_ms
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValueError("payload is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    topic_id = topic_device_id(topic)
    if not topic_id:
        raise TelemetryRejectedError("topic does not contain a device id", alert_type="format")

    payload_id = payload.get("deviceId")
    if not isinstance(payload_id, str) or not payload_id.strip():
        raise TelemetryRejectedError(
            "payload deviceId is required",
            device_id=topic_id,
            alert_type="format",
        )
    device_id = payload_id
    if len(device_id) > 128 or any(char in device_id for char in "/+#\x00"):
        raise TelemetryRejectedError("payload deviceId is invalid", device_id=topic_id)
    if device_id != topic_id:
        raise TelemetryRejectedError(
            f"payload deviceId {device_id!r} does not match topic device id {topic_id!r}",
            device_id=topic_id,
            alert_type="device_id_mismatch",
            title="Device ID Mismatch",
            level="medium",
        )

    try:
        temperature = float(payload.get("temperature"))
        humidity = float(payload.get("humidity"))
    except (TypeError, ValueError) as exc:
        raise ValueError("temperature and humidity are required numbers") from exc

    if not math.isfinite(temperature) or not math.isfinite(humidity):
        raise ValueError("temperature or humidity is not a number")

    return {
        "deviceId": device_id,
        "seq": _require_counter(payload.get("seq"), "seq"),
        "temperature": temperature,
        "humidity": humidity,
        "rssi": int(payload.get("rssi") or 0),
        "uptimeMs": _require_counter(payload.get("uptimeMs"), "uptimeMs"),
        "receivedAt": timestamp,
    }


def validate_sequence_locked(data: dict[str, Any]) -> str:
    """Validate seq/uptime before any device or telemetry mutation.

    A lower, small sequence and a significant uptime rollback indicate a
    restart. Duplicates and smaller uptime fluctuations remain suspicious.
    """
    previous = state["devices"].get(data["deviceId"])
    if previous is None:
        return "first"

    previous_seq = int(previous.get("seq", 0))
    previous_uptime = int(previous.get("uptimeMs", 0))
    sequence = int(data["seq"])
    uptime = int(data["uptimeMs"])
    uptime_rolled_back = uptime < previous_uptime

    if (
        sequence < previous_seq
        and sequence <= SEQ_RESTART_MAX
        and previous_uptime - uptime >= SEQ_RESTART_MIN_UPTIME_DROP_MS
    ):
        return "restart"

    if sequence <= previous_seq:
        raise TelemetryRejectedError(
            f"sequence {sequence} is not greater than previous sequence {previous_seq}",
            device_id=data["deviceId"],
            alert_type="sequence",
            title="Suspicious Sequence",
            level="medium",
        )

    if uptime_rolled_back:
        raise TelemetryRejectedError(
            "uptime moved backwards without a sequence reset",
            device_id=data["deviceId"],
            alert_type="sequence",
            title="Suspicious Sequence",
            level="medium",
        )
    return "normal"


def upsert_device_locked(data: dict[str, Any], sequence_event: str = "normal") -> dict[str, Any]:
    devices = state["devices"]
    previous = devices.get(data["deviceId"])
    device_number = data["deviceId"].replace("esp32_", "")

    next_device = {
        "deviceId": data["deviceId"],
        "name": previous.get("name") if previous else f"Environment Sensor Node {device_number}",
        "area": previous.get("area") if previous else "Lab Collection Area",
        "online": True,
        "status": "normal",
        "temperature": data["temperature"],
        "humidity": data["humidity"],
        "rssi": data["rssi"],
        "seq": data["seq"],
        "uptimeMs": data["uptimeMs"],
        "lastSeen": data["receivedAt"],
        "lastSeenText": format_datetime(data["receivedAt"]),
    }

    if previous is None:
        create_alert_locked("info", "New Device Connected", data["deviceId"], "The device reported telemetry via MQTT for the first time.", "new_device")
    elif not previous.get("online"):
        create_alert_locked("info", "Device Back Online", data["deviceId"], "The offline device has resumed telemetry reporting.", "online")

    if sequence_event == "restart":
        create_alert_locked("info", "Device Restarted", data["deviceId"], "The sequence and uptime counters indicate that the device restarted.", "restart")

    if previous is not None:
        elapsed = data["receivedAt"] - int(previous["lastSeen"])
        if elapsed > OFFLINE_THRESHOLD_MS * 1.5:
            create_alert_locked(
                "medium",
                "Message Interval Anomaly",
                data["deviceId"],
                f"The interval between two reports is {round(elapsed / 1000)} seconds, exceeding the normal period.",
                "frequency",
            )

    if data["temperature"] >= TEMP_ALERT_THRESHOLD:
        next_device["status"] = "warning"
        create_alert_locked(
            "high",
            "Temperature Anomaly",
            data["deviceId"],
            f"Current temperature {data['temperature']:.1f}C exceeds the {TEMP_ALERT_THRESHOLD:.0f}C threshold.",
            "temperature",
        )

    if data["humidity"] >= HUMIDITY_ALERT_THRESHOLD:
        next_device["status"] = "warning"
        create_alert_locked(
            "medium",
            "Humidity Anomaly",
            data["deviceId"],
            f"Current humidity {data['humidity']:.1f}% exceeds the {HUMIDITY_ALERT_THRESHOLD:.0f}% threshold.",
            "humidity",
        )

    devices[data["deviceId"]] = next_device
    state["telemetryHistory"].append(
        {
            "timeLabel": format_time(data["receivedAt"]),
            "deviceId": data["deviceId"],
            "temperature": data["temperature"],
            "humidity": data["humidity"],
            "rssi": data["rssi"],
            "seq": data["seq"],
            "timestamp": data["receivedAt"],
        }
    )
    del state["telemetryHistory"][:-HISTORY_LIMIT]
    return next_device


def evaluate_offline_devices_locked() -> None:
    timestamp = now_ms()
    for device in state["devices"].values():
        if device.get("online") and timestamp - int(device["lastSeen"]) > OFFLINE_THRESHOLD_MS:
            device["online"] = False
            device["status"] = "offline"
            create_alert_locked("high", "Device Offline", device["deviceId"], "No telemetry has been received for more than 15 seconds.", "offline")


def build_snapshot_locked(evaluate_offline: bool = True) -> dict[str, Any]:
    if evaluate_offline:
        evaluate_offline_devices_locked()
    devices = sorted((dict(item) for item in state["devices"].values()), key=lambda item: item["lastSeen"], reverse=True)
    online_count = len([item for item in devices if item.get("online")])
    warning_count = len([item for item in state["alerts"] if item.get("level") in {"medium", "high"}])
    avg_temperature = sum(item["temperature"] for item in devices) / len(devices) if devices else 0
    avg_humidity = sum(item["humidity"] for item in devices) / len(devices) if devices else 0

    return {
        "generatedAt": now_iso(),
        "brokerLabel": state["broker"],
        "mqttConnected": state["mqttConnected"],
        "mysqlConnected": state["mysqlConnected"],
        "mysqlEnabled": mysql_store.enabled,
        "devices": devices,
        "alerts": [dict(item) for item in state["alerts"]],
        "telemetryHistory": [dict(item) for item in state["telemetryHistory"]],
        "summary": {
            "totalDevices": len(devices),
            "onlineCount": online_count,
            "offlineCount": len(devices) - online_count,
            "warningCount": warning_count,
            "avgTemperature": f"{avg_temperature:.1f}",
            "avgHumidity": f"{avg_humidity:.1f}",
        },
    }


def get_snapshot() -> dict[str, Any]:
    with state_lock:
        return build_snapshot_locked()


class WebSocketManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, event: str, payload: dict[str, Any], received_at_ms: int | None = None) -> None:
        message = {
            "event": event,
            "backendReceivedAtMs": now_ms() if received_at_ms is None else received_at_ms,
            "payload": payload,
        }
        for websocket in list(self.connections):
            try:
                await websocket.send_json(message)
            except RuntimeError:
                self.disconnect(websocket)


ws_manager = WebSocketManager()


def schedule_broadcast(event: str, payload: dict[str, Any], received_at_ms: int | None = None) -> None:
    if app_loop is None or app_loop.is_closed():
        return
    timestamp = now_ms() if received_at_ms is None else received_at_ms
    asyncio.run_coroutine_threadsafe(ws_manager.broadcast(event, payload, timestamp), app_loop)


def process_telemetry(
    raw_payload: str,
    topic: str,
    source: str = "mqtt",
    *,
    received_at_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    telemetry = normalize_telemetry(raw_payload, topic, received_at_ms=received_at_ms)
    with state_lock:
        sequence_event = validate_sequence_locked(telemetry)
        # Sequence validation deliberately precedes upsert_device_locked and
        # save_snapshot: rejected messages cannot mutate state or telemetry.
        device = upsert_device_locked(telemetry, sequence_event=sequence_event)

    mysql_store.save_snapshot(telemetry, source=source)
    with state_lock:
        state["mysqlConnected"] = mysql_store.connected
        snapshot = build_snapshot_locked()
    return device, snapshot


def handle_valid_telemetry(raw_payload: str, topic: str, received_at_ms: int | None = None) -> None:
    device, snapshot = process_telemetry(raw_payload, topic, source="mqtt", received_at_ms=received_at_ms)
    schedule_broadcast("telemetry", {"device": device, "snapshot": snapshot}, device["lastSeen"])


def on_mqtt_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
    code = reason_code_value(reason_code)
    with state_lock:
        state["mqttConnected"] = code == 0
        snapshot = build_snapshot_locked()
    if code == 0:
        client.subscribe(MQTT_TOPIC)
    else:
        with state_lock:
            create_alert_locked("high", "MQTT Connection Failed", "server", f"reason_code={code}", "mqtt")
            snapshot = build_snapshot_locked()
    schedule_broadcast("snapshot", snapshot)


def on_mqtt_disconnect(client: mqtt.Client, userdata: Any, *args: Any) -> None:
    with state_lock:
        state["mqttConnected"] = False
        snapshot = build_snapshot_locked()
    schedule_broadcast("snapshot", snapshot)


def on_mqtt_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
    received_at_ms = now_ms()
    raw_payload = message.payload.decode("utf-8", errors="replace")
    try:
        handle_valid_telemetry(raw_payload, message.topic, received_at_ms)
        print(f"[MQTT] {message.topic} {raw_payload}")
    except ValueError as exc:
        if isinstance(exc, TelemetryRejectedError):
            device_id = exc.device_id
            alert_type = exc.alert_type
            title = exc.title
            level = exc.level
        else:
            device_id = topic_device_id(message.topic) or "unknown"
            alert_type = "format"
            title = "Invalid Data Format"
            level = "medium"
        with state_lock:
            create_alert_locked(level, title, device_id, str(exc), alert_type)
            # Do not let an invalid message trigger an unrelated offline
            # state transition while constructing its alert snapshot.
            snapshot = build_snapshot_locked(evaluate_offline=False)
        schedule_broadcast("snapshot", snapshot, received_at_ms)
        print(f"[MQTT] invalid payload: {raw_payload}")


def start_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"iiot_python_monitor_{random.randint(1000, 9999)}",
        clean_session=True,
    )
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_mqtt_connect
    client.on_disconnect = on_mqtt_disconnect
    client.on_message = on_mqtt_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


async def periodic_snapshot() -> None:
    while True:
        await asyncio.sleep(3)
        schedule_broadcast("snapshot", get_snapshot())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_loop, mqtt_client, offline_task
    validate_runtime_config()
    app_loop = asyncio.get_running_loop()
    mysql_connected = mysql_store.initialize()
    saved_alerts = mysql_store.load_alerts(ALERT_LIMIT) if mysql_connected else []
    with state_lock:
        state["mysqlConnected"] = mysql_store.connected
        state["alerts"] = saved_alerts
    mqtt_client = start_mqtt_client()
    offline_task = asyncio.create_task(periodic_snapshot())
    try:
        yield
    finally:
        if offline_task:
            offline_task.cancel()
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        mysql_store.close()


app = FastAPI(title="IIoT Security Monitor API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mqttConnected": state["mqttConnected"],
        "mysqlConnected": mysql_store.connected,
        "mysqlEnabled": mysql_store.enabled,
        "broker": state["broker"],
        "topic": MQTT_TOPIC,
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Admin credentials are not configured")
    if payload.username != ADMIN_USERNAME or payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token, expires_at = create_auth_session()
    return {
        "ok": True,
        "username": payload.username,
        "token": token,
        "tokenType": "bearer",
        "expiresAt": expires_at,
    }


@app.get("/api/dashboard")
def dashboard(_: str = Depends(require_auth)) -> dict[str, Any]:
    return get_snapshot()


@app.post("/api/telemetry", status_code=201)
async def manual_telemetry(
    payload: dict[str, Any],
    _: str = Depends(require_auth),
) -> dict[str, Any]:
    received_at_ms = now_ms()
    try:
        raw_payload = json.dumps(payload, ensure_ascii=False)
        device_id = payload.get("deviceId")
        if not isinstance(device_id, str) or not device_id.strip():
            raise TelemetryRejectedError("payload deviceId is required", alert_type="format")
        device, snapshot = process_telemetry(
            raw_payload,
            f"manual/device/{device_id}/telemetry",
            source="manual",
            received_at_ms=received_at_ms,
        )
    except ValueError as exc:
        if isinstance(exc, TelemetryRejectedError):
            alert_device_id = exc.device_id
            alert_type = exc.alert_type
            title = exc.title
            level = exc.level
        else:
            alert_device_id = str(payload.get("deviceId") or "unknown")
            alert_type = "format"
            title = "Invalid Data Format"
            level = "medium"
        with state_lock:
            create_alert_locked(level, title, alert_device_id, str(exc), alert_type)
            snapshot = build_snapshot_locked(evaluate_offline=False)
        await ws_manager.broadcast("snapshot", snapshot, received_at_ms)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await ws_manager.broadcast("telemetry", {"device": device, "snapshot": snapshot}, received_at_ms)
    return {"ok": True, "device": device}


def parse_history_date(value: str | None, field_name: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must use YYYY-MM-DD format") from exc


@app.get("/api/telemetry/history")
def telemetry_history(
    start_date: str | None = Query(default=None, alias="startDate"),
    end_date: str | None = Query(default=None, alias="endDate"),
    device_id: str | None = Query(default=None, alias="deviceId"),
    limit: int = Query(default=500, ge=1, le=1000),
    _: str = Depends(require_auth),
) -> dict[str, Any]:
    start_at = parse_history_date(start_date, "startDate")
    end_at = parse_history_date(end_date, "endDate")
    if start_at and end_at and start_at > end_at:
        raise HTTPException(status_code=400, detail="startDate must be earlier than or equal to endDate")

    if start_at:
        start_at = start_at.replace(tzinfo=timezone.utc).replace(tzinfo=None)
    if end_at:
        end_at = (end_at + timedelta(days=1)).replace(tzinfo=timezone.utc).replace(tzinfo=None)

    try:
        rows = mysql_store.query_snapshots(
            start_at=start_at,
            end_at=end_at,
            device_id=device_id,
            limit=limit,
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    items: list[dict[str, Any]] = []
    for row in rows:
        received_at = row.get("received_at")
        received_at_text = received_at.isoformat(sep=" ") if isinstance(received_at, datetime) else str(received_at)
        payload_json = row.get("payload_json")
        if isinstance(payload_json, str):
            try:
                payload_json = json.loads(payload_json)
            except json.JSONDecodeError:
                pass
        items.append(
            {
                "id": int(row["id"]),
                "deviceId": row["device_id"],
                "seq": int(row["seq"]),
                "temperature": float(row["temperature"]),
                "humidity": float(row["humidity"]),
                "rssi": int(row["rssi"]),
                "uptimeMs": int(row["uptime_ms"]),
                "receivedAt": received_at_text,
                "receivedAtMs": int(row["received_at_ms"]),
                "source": row["source"],
                "payload": payload_json,
            }
        )

    return {
        "items": items,
        "total": len(items),
        "startDate": start_date,
        "endDate": end_date,
        "mysqlConnected": mysql_store.connected,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    received_at_ms = now_ms()
    if not is_valid_auth_token(websocket.query_params.get("token")):
        await websocket.close(code=1008)
        return
    await ws_manager.connect(websocket)
    await websocket.send_json({"event": "snapshot", "backendReceivedAtMs": received_at_ms, "payload": get_snapshot()})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=HTTP_PORT, reload=True)
