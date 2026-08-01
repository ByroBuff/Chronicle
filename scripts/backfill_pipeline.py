"""Backfill language detection/translation, embeddings, and story
clustering for articles ingested before this pipeline existed.

Processes oldest-first in batches. Safe to interrupt and re-run: each
batch is drawn from articles that still have no story_id, and assigning a
story is the last step of processing an article, so a batch is either
fully applied or (on error) rolled back and retried untouched next run.

Examples:
    python -m scripts.backfill_pipeline
    python -m scripts.backfill_pipeline --batch-size 50 --limit 500
    python -m scripts.backfill_pipeline --redo
"""

import argparse


def fetch_pending_articles(
    conn,
    batch_size: int,
    redo: bool,
) -> list:
    where_clause = "" if redo else "WHERE story_id IS NULL"

    return conn.execute(
        f"""
        SELECT article_id, title, clean_text
        FROM articles
        {where_clause}
        ORDER BY article_id ASC
        LIMIT ?
        """,
        (batch_size,),
    ).fetchall()


def backfill(
    batch_size: int,
    redo: bool,
    limit: int | None,
) -> None:
    # Import heavy modules lazily so argument parsing stays fast and
    # testable without spaCy/fastembed/Argos Translate present.
    import vector_store
    from database import get_connection, setup_database
    from workers.clustering import assign_story
    from workers.embeddings import embed_texts
    from workers.language import detect_language, translate_to_english

    setup_database()

    processed = 0

    while limit is None or processed < limit:
        fetch_limit = batch_size

        if limit is not None:
            fetch_limit = min(batch_size, limit - processed)

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            rows = fetch_pending_articles(cursor, fetch_limit, redo)

            if not rows:
                break

            texts: list[tuple[int, str]] = []

            for article_id, title, clean_text in rows:
                clean_text = clean_text or ""
                language = detect_language(clean_text) or "en"

                if language == "en":
                    translated_title = title
                    translated_text = clean_text
                else:
                    translated_title = (
                        translate_to_english(title, language)
                        if title
                        else title
                    )
                    translated_text = translate_to_english(
                        clean_text,
                        language,
                    )

                cursor.execute(
                    """
                    UPDATE articles
                    SET title = ?, clean_text = ?, language = ?
                    WHERE article_id = ?
                    """,
                    (
                        translated_title,
                        translated_text,
                        language,
                        article_id,
                    ),
                )

                texts.append((article_id, translated_text))

            embeddings = embed_texts(
                [text for _, text in texts]
            )

            for (article_id, _), embedding in zip(
                texts,
                embeddings,
                strict=True,
            ):
                vector_store.upsert_article_embedding(
                    conn,
                    article_id,
                    embedding,
                )

                assign_story(conn, article_id, embedding)

        processed += len(rows)

        print(
            f"Backfilled {processed} article(s)...",
            flush=True,
        )

    print(
        f"Done: {processed} article(s) backfilled.",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill translation, embeddings, and story clustering "
            "for articles ingested before this pipeline existed."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Articles to process per transaction (default: 25).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many articles (default: no limit).",
    )
    parser.add_argument(
        "--redo",
        action="store_true",
        help="Reprocess articles that already have a story_id.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    backfill(
        batch_size=args.batch_size,
        redo=args.redo,
        limit=args.limit,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
