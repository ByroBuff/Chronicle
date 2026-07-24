import asyncio
from dataclasses import dataclass

from database import get_connection, setup_database
from workers.entity_extractor import extract_entities_batch
from workers.scraper import (
    ArticleInput,
    ScrapedArticle,
    fetch_article_batch,
)


MAX_BATCH_SIZE = 5


@dataclass(frozen=True)
class ProcessedArticle:
    article: ScrapedArticle
    entities: set[tuple[str, str]]


def insert_batch(
    articles: list[ProcessedArticle],
) -> int:
    if not articles:
        return 0

    inserted = 0

    # One connection and one transaction for the entire batch.
    with get_connection() as conn:
        cursor = conn.cursor()

        # Acquire SQLite's write reservation before changing anything.
        cursor.execute("BEGIN IMMEDIATE")

        for processed in articles:
            article = processed.article

            cursor.execute(
                """
                INSERT OR IGNORE INTO articles (
                    url,
                    title,
                    published,
                    clean_text
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    article.url,
                    article.title,
                    article.published,
                    article.clean_text,
                ),
            )

            # Another batch or worker already inserted this URL.
            if cursor.rowcount == 0:
                print(
                    f"Already exists: {article.url}",
                    flush=True,
                )
                continue

            article_id = cursor.lastrowid
            inserted += 1

            for entity_type, canonical_name in processed.entities:
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
                        canonical_name,
                    ),
                )

                entity_row = cursor.execute(
                    """
                    SELECT entity_id
                    FROM entities
                    WHERE entity_type = ?
                      AND canonical_name = ?
                    """,
                    (
                        entity_type,
                        canonical_name,
                    ),
                ).fetchone()

                if entity_row is None:
                    raise RuntimeError(
                        "Entity could not be retrieved after insertion"
                    )

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
                        entity_row[0],
                    ),
                )

        # The connection context commits all articles together.
        # An exception rolls the entire batch back.

    return inserted


async def process_batch_async(
    article_data: list[dict],
) -> list[ProcessedArticle]:
    articles = [
        ArticleInput(
            url=item["url"],
            title=item["title"],
            published=item.get("published"),
        )
        for item in article_data
    ]

    print(
        f"Fetching batch of {len(articles)} articles",
        flush=True,
    )

    scraped_articles = await fetch_article_batch(
        articles
    )

    if not scraped_articles:
        return []

    print(
        f"Running NLP on {len(scraped_articles)} articles",
        flush=True,
    )

    # nlp.pipe is synchronous, so keep it off the asyncio event loop.
    entity_sets = await asyncio.to_thread(
        extract_entities_batch,
        [
            article.clean_text
            for article in scraped_articles
        ],
    )

    return [
        ProcessedArticle(
            article=article,
            entities=entities,
        )
        for article, entities in zip(
            scraped_articles,
            entity_sets,
            strict=True,
        )
    ]


def process_article_batch(
    article_data: list[dict],
) -> dict:
    if not article_data:
        return {
            "received": 0,
            "processed": 0,
            "inserted": 0,
        }

    if len(article_data) > MAX_BATCH_SIZE:
        raise ValueError(
            f"Batch contains {len(article_data)} articles; "
            f"maximum is {MAX_BATCH_SIZE}"
        )

    setup_database()

    processed_articles = asyncio.run(
        process_batch_async(article_data)
    )

    inserted = insert_batch(
        processed_articles
    )

    result = {
        "received": len(article_data),
        "processed": len(processed_articles),
        "inserted": inserted,
    }

    print(
        f"Batch complete: {result}",
        flush=True,
    )

    return result