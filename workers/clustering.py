"""Groups articles into "stories" — a story is an incrementally maintained
centroid of the embeddings of the articles assigned to it. A new article
joins the nearest story if it is similar enough and that story is still
recent; otherwise it starts a new story.
"""

import os
import sqlite3
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import vector_store


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "clustering.toml"
)

CONFIG_PATH = Path(
    os.getenv(
        "CLUSTERING_CONFIG_PATH",
        str(DEFAULT_CONFIG_PATH),
    )
)


def _load_clustering_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Clustering configuration does not exist: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open("rb") as handle:
        config = tomllib.load(handle)

    return config.get("clustering", {})


_CONFIG = _load_clustering_config()

SIMILARITY_THRESHOLD = float(_CONFIG.get("similarity_threshold", 0.82))
RECENCY_WINDOW_DAYS = float(_CONFIG.get("recency_window_days", 14))

MAX_COSINE_DISTANCE = 1.0 - SIMILARITY_THRESHOLD


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _within_recency_window(updated_at: str) -> bool:
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return False

    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)

    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_WINDOW_DAYS)

    return updated >= cutoff


def _running_mean(
    old_centroid: list[float] | None,
    article_count: int,
    new_embedding: list[float],
) -> list[float]:
    if old_centroid is None or article_count <= 0:
        return new_embedding

    return [
        (old * article_count + new) / (article_count + 1)
        for old, new in zip(old_centroid, new_embedding, strict=True)
    ]


def assign_story(
    conn: sqlite3.Connection,
    article_id: int,
    embedding: list[float],
) -> int:
    """Attach article_id to the nearest sufficiently-similar recent story,
    creating a new story when none qualifies. Returns the story_id."""
    story_id: int | None = None
    article_count = 0

    nearest = vector_store.find_nearest_story(conn, embedding)

    if nearest is not None:
        candidate_story_id, distance = nearest

        if distance <= MAX_COSINE_DISTANCE:
            row = conn.execute(
                """
                SELECT article_count, updated_at
                FROM stories
                WHERE story_id = ?
                """,
                (candidate_story_id,),
            ).fetchone()

            if row is not None and _within_recency_window(row[1]):
                story_id = candidate_story_id
                article_count = row[0]

    now = _utcnow_iso()

    if story_id is None:
        cursor = conn.execute(
            """
            INSERT INTO stories (created_at, updated_at, article_count)
            VALUES (?, ?, 1)
            """,
            (now, now),
        )
        story_id = cursor.lastrowid

        vector_store.upsert_story_centroid(conn, story_id, embedding)

    else:
        old_centroid = vector_store.get_story_centroid(conn, story_id)
        new_centroid = _running_mean(old_centroid, article_count, embedding)

        vector_store.upsert_story_centroid(conn, story_id, new_centroid)

        conn.execute(
            """
            UPDATE stories
            SET updated_at = ?, article_count = article_count + 1
            WHERE story_id = ?
            """,
            (now, story_id),
        )

    conn.execute(
        "UPDATE articles SET story_id = ? WHERE article_id = ?",
        (story_id, article_id),
    )

    return story_id
