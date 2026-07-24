import sqlite3
from collections.abc import Generator

from database import DB_PATH


def create_read_connection() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        raise RuntimeError(
            f"Database file does not exist: {DB_PATH}"
        )

    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=30,
        check_same_thread=False,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")

    return connection


def get_database() -> Generator[
    sqlite3.Connection,
    None,
    None,
]:
    connection = create_read_connection()

    try:
        yield connection
    finally:
        connection.close()