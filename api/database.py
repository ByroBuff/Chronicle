import os
import sqlite3
from collections.abc import Generator
from pathlib import Path


DB_PATH = Path(os.getenv("DB_PATH"))


def create_read_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{DB_PATH}?mode=ro",
        uri=True,
        timeout=10,
        check_same_thread=False,
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def get_database() -> Generator[sqlite3.Connection, None, None]:
    connection = create_read_connection()

    try:
        yield connection
    finally:
        connection.close()