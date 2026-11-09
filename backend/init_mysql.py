"""Create the configured database and tables without changing existing data."""

import logging

import pymysql

from database import MySQLSnapshotStore


def initialize_database() -> None:
    store = MySQLSnapshotStore()
    if not store.enabled:
        raise ValueError("Set MYSQL_ENABLED=true before initializing MySQL")
    if not store.password:
        raise ValueError("MYSQL_PASSWORD must be supplied through the environment")

    # MySQLSnapshotStore validates the database/table identifiers on creation.
    connection = pymysql.connect(
        host=store.host,
        port=store.port,
        user=store.user,
        password=store.password,
        charset="utf8mb4",
        connect_timeout=store.connect_timeout,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{store.database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        connection.close()

    try:
        if not store.initialize():
            raise RuntimeError("Database exists, but table initialization failed; see the MySQL error above")
        print(f"MySQL ready: {store.host}:{store.port}/{store.database}")
        print(f"Tables ready: {store.table}, alerts")
    finally:
        store.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        initialize_database()
    except (ValueError, RuntimeError, pymysql.MySQLError) as exc:
        raise SystemExit(f"MySQL initialization failed: {exc}") from exc
