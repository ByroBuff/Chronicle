import sqlite3
from workers.entity_extractor import extract_entities
from workers.scraper import fetch_article_body

def process_article(url, title, published):
    conn = sqlite3.connect("custom_gdelt.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT article_id FROM articles WHERE url=?",
        (url,)
    )

    if cursor.fetchone():
        print(f"Already exists: {url}")
        conn.close()
        return

    print(f"Processing {title}")

    clean_text = fetch_article_body(url)

    if not clean_text:
        conn.close()
        return

    cursor.execute("""
        INSERT INTO articles (
            url,
            title,
            published,
            clean_text
        )
        VALUES (?, ?, ?, ?)
    """, (
        url,
        title,
        published,
        clean_text
    ))

    article_id = cursor.lastrowid

    entities = extract_entities(clean_text)

    for entity_type, name in entities:

        cursor.execute("""
            INSERT OR IGNORE INTO entities (
                entity_type,
                canonical_name
            )
            VALUES (?, ?)
        """, (
            entity_type,
            name
        ))

        cursor.execute("""
            SELECT entity_id
            FROM entities
            WHERE entity_type=?
            AND canonical_name=?
        """, (
            entity_type,
            name,
        ))

        entity_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT OR IGNORE
            INTO article_entities (
                article_id,
                entity_id
            )
            VALUES (?, ?)
        """, (
            article_id,
            entity_id
        ))

    conn.commit()
    conn.close()

    print(f"Saved: {title}")