import os
import sqlite3
from pathlib import Path


DB_PATH = Path(
    os.getenv(
        "DB_PATH",
        "/data/chronicle.db",
    )
)


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=30,
    )

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    return conn


def setup_database() -> None:
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                article_id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT,
                published TEXT,
                clean_text TEXT
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS entities (
                entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                UNIQUE(entity_type, canonical_name)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS article_entities (
                article_id INTEGER NOT NULL,
                entity_id INTEGER NOT NULL,

                PRIMARY KEY(article_id, entity_id),

                FOREIGN KEY(article_id)
                    REFERENCES articles(article_id)
                    ON DELETE CASCADE,

                FOREIGN KEY(entity_id)
                    REFERENCES entities(entity_id)
                    ON DELETE CASCADE
            )
            """
        )