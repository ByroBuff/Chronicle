"""Shared sqlite-vec access for article embeddings and per-story centroids.

Vectors live as vec0 virtual tables inside the same SQLite file as the rest
of the schema (see database.py). This module is deliberately dependency-light
(sqlite_vec only) so importing it does not pull in fastembed/spaCy, mirroring
how metrics.py stays import-cheap for the API process.
"""

import sqlite3
import struct


import sqlite_vec


EMBEDDING_DIMENSIONS = 384


def load_vec_extension(conn: sqlite3.Connection) -> None:
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def ensure_vector_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS article_vectors USING vec0(
            article_id INTEGER PRIMARY KEY,
            embedding FLOAT[{EMBEDDING_DIMENSIONS}] distance_metric=cosine
        )
        """
    )

    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS story_centroids USING vec0(
            story_id INTEGER PRIMARY KEY,
            embedding FLOAT[{EMBEDDING_DIMENSIONS}] distance_metric=cosine
        )
        """
    )


def serialize(embedding: list[float]) -> bytes:
    return sqlite_vec.serialize_float32(embedding)


def deserialize(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def upsert_article_embedding(
    conn: sqlite3.Connection,
    article_id: int,
    embedding: list[float],
) -> None:
    conn.execute(
        "DELETE FROM article_vectors WHERE article_id = ?",
        (article_id,),
    )

    conn.execute(
        """
        INSERT INTO article_vectors (article_id, embedding)
        VALUES (?, ?)
        """,
        (
            article_id,
            serialize(embedding),
        ),
    )


def upsert_story_centroid(
    conn: sqlite3.Connection,
    story_id: int,
    embedding: list[float],
) -> None:
    conn.execute(
        "DELETE FROM story_centroids WHERE story_id = ?",
        (story_id,),
    )

    conn.execute(
        """
        INSERT INTO story_centroids (story_id, embedding)
        VALUES (?, ?)
        """,
        (
            story_id,
            serialize(embedding),
        ),
    )


def get_article_embedding(
    conn: sqlite3.Connection,
    article_id: int,
) -> list[float] | None:
    row = conn.execute(
        """
        SELECT embedding
        FROM article_vectors
        WHERE article_id = ?
        """,
        (article_id,),
    ).fetchone()

    if row is None:
        return None

    return deserialize(row[0])


def find_similar_articles(
    conn: sqlite3.Connection,
    embedding: list[float],
    limit: int,
    exclude_article_id: int | None = None,
) -> list[tuple[int, float]]:
    """Return up to `limit` (article_id, cosine_distance) pairs, nearest first."""
    # Over-fetch by one so excluding the source article still leaves `limit`.
    k = limit + 1 if exclude_article_id is not None else limit

    rows = conn.execute(
        """
        SELECT article_id, distance
        FROM article_vectors
        WHERE embedding MATCH ?
          AND k = ?
        ORDER BY distance
        """,
        (
            serialize(embedding),
            k,
        ),
    ).fetchall()

    results = [
        (row[0], row[1])
        for row in rows
        if row[0] != exclude_article_id
    ]

    return results[:limit]


def get_story_centroid(
    conn: sqlite3.Connection,
    story_id: int,
) -> list[float] | None:
    row = conn.execute(
        """
        SELECT embedding
        FROM story_centroids
        WHERE story_id = ?
        """,
        (story_id,),
    ).fetchone()

    if row is None:
        return None

    return deserialize(row[0])


def find_nearest_story(
    conn: sqlite3.Connection,
    embedding: list[float],
) -> tuple[int, float] | None:
    """Return the (story_id, cosine_distance) of the closest story centroid."""
    row = conn.execute(
        """
        SELECT story_id, distance
        FROM story_centroids
        WHERE embedding MATCH ?
          AND k = 1
        ORDER BY distance
        """,
        (serialize(embedding),),
    ).fetchone()

    if row is None:
        return None

    return row[0], row[1]
