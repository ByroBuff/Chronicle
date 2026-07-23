import sqlite3


def get_connection():
    return sqlite3.connect("custom_gdelt.db")


def setup_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            article_id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            title TEXT,
            published TEXT,
            clean_text TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            UNIQUE(entity_type, canonical_name)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS article_entities (
            article_id INTEGER,
            entity_id INTEGER,
            PRIMARY KEY(article_id, entity_id),

            FOREIGN KEY(article_id)
                REFERENCES articles(article_id),

            FOREIGN KEY(entity_id)
                REFERENCES entities(entity_id)
        )
    """)

    conn.commit()
    conn.close()