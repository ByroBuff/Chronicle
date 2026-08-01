import os
import sqlite3
from pathlib import Path

from vector_store import ensure_vector_tables, load_vec_extension


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

    load_vec_extension(conn)

    return conn


def _add_column_if_missing(
    cursor: sqlite3.Cursor,
    table: str,
    column: str,
    ddl: str,
) -> None:
    existing = {
        row[1]
        for row in cursor.execute(f"PRAGMA table_info({table})")
    }

    if column not in existing:
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN {ddl}"
        )


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

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS stories (
                story_id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                article_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # articles.language / articles.story_id were added after the initial
        # release, so existing databases need an idempotent migration here
        # rather than a fresh CREATE TABLE.
        _add_column_if_missing(
            cursor,
            "articles",
            "language",
            "language TEXT",
        )

        _add_column_if_missing(
            cursor,
            "articles",
            "story_id",
            "story_id INTEGER REFERENCES stories(story_id)",
        )

        _add_column_if_missing(
            cursor,
            "stories",
            "label",
            "label TEXT",
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_articles_story_id
                ON articles(story_id)
            """
        )

        ensure_vector_tables(conn)