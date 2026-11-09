from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import pymysql
from pymysql.connections import Connection


logger = logging.getLogger(__name__)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


class DatabaseUnavailableError(RuntimeError):
    pass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class MySQLSnapshotStore:
    """Persist accepted telemetry snapshots and deduplicated alerts."""

    def __init__(self) -> None:
        self.enabled = _env_bool("MYSQL_ENABLED", True)
        self.host = os.getenv("MYSQL_HOST", "127.0.0.1")
        self.port = int(os.getenv("MYSQL_PORT", "3306"))
        self.user = os.getenv("MYSQL_USER", "root")
        self.password = os.getenv("MYSQL_PASSWORD")
        self.database = os.getenv("MYSQL_DATABASE", "iiot_monitor")
        self.table = os.getenv("MYSQL_TABLE", "telemetry_snapshots")
        self.connect_timeout = int(os.getenv("MYSQL_CONNECT_TIMEOUT", "5"))
        self._connection: Connection | None = None
        self._lock = Lock()
        self._connected = False
        self._validate_identifiers()

    @property
    def connected(self) -> bool:
        return self._connected

    def _validate_identifiers(self) -> None:
        for name, value in (("MYSQL_DATABASE", self.database), ("MYSQL_TABLE", self.table)):
            if not _IDENTIFIER_RE.fullmatch(value):
                raise ValueError(f"{name} must contain only letters, numbers, and underscores")

    def _table_sql(self) -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS `{self.table}` (
                `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `device_id` VARCHAR(128) NOT NULL,
                `seq` BIGINT NOT NULL DEFAULT 0,
                `temperature` DECIMAL(10, 2) NOT NULL,
                `humidity` DECIMAL(10, 2) NOT NULL,
                `rssi` SMALLINT NOT NULL DEFAULT 0,
                `uptime_ms` BIGINT NOT NULL DEFAULT 0,
                `received_at` DATETIME(3) NOT NULL,
                `received_at_ms` BIGINT NOT NULL,
                `source` VARCHAR(16) NOT NULL DEFAULT 'mqtt',
                `payload_json` JSON NULL,
                PRIMARY KEY (`id`),
                KEY `idx_device_received_at` (`device_id`, `received_at`),
                KEY `idx_received_at` (`received_at`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """

    def _alerts_table_sql(self) -> str:
        return """
            CREATE TABLE IF NOT EXISTS `alerts` (
                `id` VARCHAR(128) NOT NULL,
                `level` VARCHAR(16) NOT NULL,
                `title` VARCHAR(255) NOT NULL,
                `device_id` VARCHAR(128) NOT NULL,
                `description` TEXT NOT NULL,
                `type` VARCHAR(64) NOT NULL,
                `first_seen_ms` BIGINT NOT NULL,
                `last_seen_ms` BIGINT NOT NULL,
                `occurrence_count` INT UNSIGNED NOT NULL DEFAULT 1,
                `created_at` DATETIME(3) NOT NULL,
                PRIMARY KEY (`id`),
                KEY `idx_alert_device_last_seen` (`device_id`, `last_seen_ms`),
                KEY `idx_alert_last_seen` (`last_seen_ms`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """

    def _close_locked(self) -> None:
        connection = self._connection
        self._connection = None
        self._connected = False
        if connection is not None:
            try:
                connection.close()
            except Exception:
                logger.debug("Failed to close MySQL connection", exc_info=True)

    def _connect_locked(self) -> bool:
        if not self.enabled:
            self._connected = False
            return False

        if not self.password:
            raise ValueError("MYSQL_PASSWORD must be set when MYSQL_ENABLED is true")

        self._connection = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            connect_timeout=self.connect_timeout,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )
        with self._connection.cursor() as cursor:
            cursor.execute(self._table_sql())
            cursor.execute(self._alerts_table_sql())
        self._connection.commit()
        self._connected = True
        logger.info("MySQL snapshot storage connected: %s:%s/%s", self.host, self.port, self.database)
        return True

    def initialize(self) -> bool:
        if not self.enabled:
            logger.info("MySQL snapshot storage is disabled by MYSQL_ENABLED")
            return False

        with self._lock:
            try:
                return self._connect_locked()
            except Exception:
                self._close_locked()
                logger.warning(
                    "MySQL snapshot storage is unavailable; realtime monitoring will continue without persistence",
                    exc_info=True,
                )
                return False

    def _ensure_connection_locked(self) -> bool:
        if self._connection is None:
            return self._connect_locked()
        self._connection.ping(reconnect=True)
        self._connected = True
        return True

    def save_snapshot(self, telemetry: dict[str, Any], source: str = "mqtt") -> bool:
        if not self.enabled:
            return False

        received_at_ms = int(telemetry["receivedAt"])
        received_at = datetime.fromtimestamp(received_at_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        payload = {
            "deviceId": telemetry["deviceId"],
            "seq": telemetry["seq"],
            "temperature": telemetry["temperature"],
            "humidity": telemetry["humidity"],
            "rssi": telemetry["rssi"],
            "uptimeMs": telemetry["uptimeMs"],
        }

        with self._lock:
            try:
                if not self._ensure_connection_locked():
                    return False
                query = f"""
                    INSERT INTO `{self.table}`
                    (device_id, seq, temperature, humidity, rssi, uptime_ms,
                     received_at, received_at_ms, source, payload_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        query,
                        (
                            telemetry["deviceId"],
                            telemetry["seq"],
                            telemetry["temperature"],
                            telemetry["humidity"],
                            telemetry["rssi"],
                            telemetry["uptimeMs"],
                            received_at,
                            received_at_ms,
                            source,
                            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        ),
                    )
                self._connection.commit()
                self._connected = True
                return True
            except Exception:
                if self._connection is not None:
                    try:
                        self._connection.rollback()
                    except Exception:
                        logger.debug("Failed to rollback MySQL transaction", exc_info=True)
                self._close_locked()
                logger.warning("Failed to save telemetry snapshot to MySQL", exc_info=True)
                return False

    def save_alert(self, alert: dict[str, Any], merged: bool = False) -> bool:
        """Insert a new alert or persist a deduplication update.

        Alerts are written independently from telemetry.  A database outage
        therefore only affects persistence; the in-memory alert remains
        available to realtime clients.
        """
        if not self.enabled:
            return False

        first_seen_ms = int(alert.get("firstSeenMs", alert.get("timestamp", 0)))
        last_seen_ms = int(alert.get("lastSeenMs", alert.get("timestamp", first_seen_ms)))
        occurrence_count = max(1, int(alert.get("occurrenceCount", 1)))
        created_at = datetime.fromtimestamp(first_seen_ms / 1000, tz=timezone.utc).replace(tzinfo=None)

        with self._lock:
            try:
                if not self._ensure_connection_locked():
                    return False
                with self._connection.cursor() as cursor:
                    if merged:
                        query = """
                            UPDATE `alerts`
                            SET `level` = %s,
                                `description` = %s,
                                `last_seen_ms` = %s,
                                `occurrence_count` = %s
                            WHERE `id` = %s
                        """
                        cursor.execute(query, (
                            alert["level"],
                            alert["description"],
                            last_seen_ms,
                            occurrence_count,
                            alert["id"],
                        ))
                    # A prior INSERT may have failed during an outage. Recover
                    # the row on the next merge, keeping the complete count.
                    if not merged or cursor.rowcount == 0:
                        query = """
                        INSERT INTO `alerts`
                        (`id`, `level`, `title`, `device_id`, `description`, `type`,
                         `first_seen_ms`, `last_seen_ms`, `occurrence_count`, `created_at`)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            `last_seen_ms` = GREATEST(`last_seen_ms`, %s),
                            `occurrence_count` = GREATEST(`occurrence_count`, %s),
                            `level` = %s,
                            `description` = %s
                        """
                        cursor.execute(query, (
                            alert["id"],
                            alert["level"],
                            alert["title"],
                            alert["deviceId"],
                            alert["description"],
                            alert["type"],
                            first_seen_ms,
                            last_seen_ms,
                            occurrence_count,
                            created_at,
                            last_seen_ms,
                            occurrence_count,
                            alert["level"],
                            alert["description"],
                        ))
                self._connection.commit()
                self._connected = True
                return True
            except Exception:
                if self._connection is not None:
                    try:
                        self._connection.rollback()
                    except Exception:
                        logger.debug("Failed to rollback MySQL alert transaction", exc_info=True)
                self._close_locked()
                logger.warning("Failed to save alert to MySQL", exc_info=True)
                return False

    def load_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Restore the newest persisted alerts for display and deduplication."""
        if not self.enabled:
            return []
        with self._lock:
            try:
                if not self._ensure_connection_locked():
                    return []
                with self._connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT id, level, title, device_id, description, type,
                               first_seen_ms, last_seen_ms, occurrence_count
                        FROM `alerts`
                        ORDER BY last_seen_ms DESC, id DESC
                        LIMIT %s
                    """, (max(1, int(limit)),))
                    rows = cursor.fetchall()
                return [{
                    "id": row["id"],
                    "level": row["level"] if row["level"] in {"info", "low", "medium", "high"} else "medium",
                    "title": row["title"],
                    "deviceId": row["device_id"],
                    "description": row["description"],
                    "type": row["type"],
                    "timestamp": int(row["last_seen_ms"]),
                    "firstSeenMs": int(row["first_seen_ms"]),
                    "lastSeenMs": int(row["last_seen_ms"]),
                    "occurrenceCount": int(row["occurrence_count"]),
                } for row in rows]
            except Exception:
                self._close_locked()
                logger.warning("Failed to load alerts from MySQL", exc_info=True)
                return []

    def query_snapshots(
        self,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        device_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            raise DatabaseUnavailableError("MySQL snapshot storage is disabled")

        clauses: list[str] = []
        params: list[Any] = []
        if start_at is not None:
            clauses.append("received_at >= %s")
            params.append(start_at)
        if end_at is not None:
            clauses.append("received_at < %s")
            params.append(end_at)
        if device_id:
            clauses.append("device_id = %s")
            params.append(device_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT id, device_id, seq, temperature, humidity, rssi, uptime_ms,
                   received_at, received_at_ms, source, payload_json
            FROM `{self.table}`
            {where_sql}
            ORDER BY received_at DESC, id DESC
            LIMIT %s
        """
        params.append(max(1, min(int(limit), 1000)))

        with self._lock:
            try:
                if not self._ensure_connection_locked():
                    raise DatabaseUnavailableError("MySQL snapshot storage is unavailable")
                with self._connection.cursor() as cursor:
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                self._connected = True
                return list(rows)
            except DatabaseUnavailableError:
                raise
            except Exception as exc:
                self._close_locked()
                logger.warning("Failed to query telemetry snapshots from MySQL", exc_info=True)
                raise DatabaseUnavailableError("MySQL snapshot storage is unavailable") from exc

    def close(self) -> None:
        with self._lock:
            self._close_locked()
