import asyncio
import dataclasses
import time
from dataclasses import dataclass

import metrics
import vector_store
from database import get_connection, setup_database
from workers.clustering import assign_story
from workers.embeddings import embed_texts
from workers.entity_extractor import extract_entities_batch
from workers.language import detect_language, translate_to_english
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


def translate_article(article: ScrapedArticle) -> ScrapedArticle:
    """Detect the article's language and translate it to English so every
    downstream stage (NER, embeddings, clustering) sees English text."""
    language = detect_language(article.clean_text) or "en"

    if language == "en":
        return dataclasses.replace(article, language=language)

    translated_title = (
        translate_to_english(article.title, language)
        if article.title
        else article.title
    )

    translated_text = translate_to_english(article.clean_text, language)

    return dataclasses.replace(
        article,
        title=translated_title,
        clean_text=translated_text,
        language=language,
    )


def insert_batch(
    articles: list[ProcessedArticle],
) -> list[tuple[int, ProcessedArticle]]:
    if not articles:
        return []

    inserted: list[tuple[int, ProcessedArticle]] = []

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
                    clean_text,
                    language
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    article.url,
                    article.title,
                    article.published,
                    article.clean_text,
                    article.language,
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
            inserted.append((article_id, processed))

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


def embed_and_cluster_batch(
    inserted: list[tuple[int, ProcessedArticle]],
) -> None:
    """Embed each newly inserted article and fold it into a story. Runs as
    its own step/transaction after insert_batch commits, so an embedding
    or clustering failure never rolls back the article insert itself."""
    if not inserted:
        return

    texts = [
        processed.article.clean_text
        for _, processed in inserted
    ]

    try:
        embeddings = embed_texts(texts)
    except Exception as exc:
        print(
            f"Embedding failed for batch: {exc}",
            flush=True,
        )
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        for (article_id, _), embedding in zip(
            inserted,
            embeddings,
            strict=True,
        ):
            vector_store.upsert_article_embedding(
                conn,
                article_id,
                embedding,
            )

            assign_story(conn, article_id, embedding)


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
        f"Translating {len(scraped_articles)} articles",
        flush=True,
    )

    # Detection/translation is CPU-bound, so keep it off the event loop.
    translated_articles = await asyncio.gather(
        *[
            asyncio.to_thread(translate_article, article)
            for article in scraped_articles
        ]
    )

    print(
        f"Running NLP on {len(translated_articles)} articles",
        flush=True,
    )

    # nlp.pipe is synchronous, so keep it off the asyncio event loop.
    entity_sets = await asyncio.to_thread(
        extract_entities_batch,
        [
            article.clean_text
            for article in translated_articles
        ],
    )

    return [
        ProcessedArticle(
            article=article,
            entities=entities,
        )
        for article, entities in zip(
            translated_articles,
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

    started_at = time.monotonic()

    processed_articles = asyncio.run(
        process_batch_async(article_data)
    )

    inserted = insert_batch(
        processed_articles
    )

    embed_and_cluster_batch(inserted)

    duration_seconds = time.monotonic() - started_at

    result = {
        "received": len(article_data),
        "processed": len(processed_articles),
        "inserted": len(inserted),
    }

    # received / scraped (processed) / ingested (inserted) throughput.
    metrics.record_batch(
        received=len(article_data),
        scraped=len(processed_articles),
        ingested=len(inserted),
        duration_seconds=duration_seconds,
    )

    print(
        f"Batch complete: {result}",
        flush=True,
    )

    return result