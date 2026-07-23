from database import get_connection, setup_database
from workers.entity_extractor import extract_entities
from workers.scraper import fetch_article_body


def process_article(
    url: str,
    title: str,
    published: str | None,
) -> None:
    setup_database()

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT article_id
            FROM articles
            WHERE url = ?
            """,
            (url,),
        )

        if cursor.fetchone():
            print(f"Already exists: {url}", flush=True)
            return

        print(f"Processing: {title}", flush=True)

        clean_text = fetch_article_body(url)

        if not clean_text:
            print(f"No article text extracted: {url}", flush=True)
            return

        cursor.execute(
            """
            INSERT INTO articles (
                url,
                title,
                published,
                clean_text
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                url,
                title,
                published,
                clean_text,
            ),
        )

        article_id = cursor.lastrowid

        for entity_type, name in extract_entities(clean_text):
            cursor.execute(
                """
                INSERT OR IGNORE INTO entities (
                    entity_type,
                    canonical_name
                )
                VALUES (?, ?)
                """,
                (
                    entity_type,
                    name,
                ),
            )

            cursor.execute(
                """
                SELECT entity_id
                FROM entities
                WHERE entity_type = ?
                  AND canonical_name = ?
                """,
                (
                    entity_type,
                    name,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                continue

            entity_id = row[0]

            cursor.execute(
                """
                INSERT OR IGNORE INTO article_entities (
                    article_id,
                    entity_id
                )
                VALUES (?, ?)
                """,
                (
                    article_id,
                    entity_id,
                ),
            )

    print(f"Saved: {title}", flush=True)