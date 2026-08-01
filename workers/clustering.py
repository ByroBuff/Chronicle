"""Groups articles into "stories" — a story is an incrementally maintained
centroid of the embeddings of the articles assigned to it. A new article
joins the nearest story if it is similar enough and that story is still
recent; otherwise it starts a new story.
"""

import os
import re
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

# Words too generic to convey what a story is about, plus common wire-copy
# filler ("says", "amid", ...) that shows up across unrelated headlines.
_LABEL_STOPWORDS = frozenset(
    """
    a an the and or but if then else for nor so yet of to in on at by
    with from into onto over under about above below after before during
    is are was were be been being has have had do does did will would
    can could shall should may might must not no yes it its it's this
    that these those as than too very just also more most less least
    new says say said amid amidst report reports reported update updates
    updated live breaking news video watch photos analysis explainer
    what why who how when where their his her our your my
    """.split()
)

_LABEL_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")

_LABEL_MAX_WORDS = 6


def _title_keywords(title: str) -> list[str]:
    """Significant, deduplicated words from a single title, in order."""
    seen: set[str] = set()
    keywords: list[str] = []

    for match in _LABEL_WORD_RE.finditer(title):
        word = match.group(0)
        lower = word.lower()

        if len(word) < 3 or lower in _LABEL_STOPWORDS or lower in seen:
            continue

        seen.add(lower)
        keywords.append(word)

    return keywords


def derive_story_label(titles: list[str]) -> str | None:
    """Summarize a story's articles as a short, human-readable label.

    Words are ranked by how many of the story's titles they appear in, so
    the label converges on what the articles have in common rather than
    whichever headline happened to join most recently.
    """
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    order: list[str] = []

    for title in titles:
        if not title:
            continue

        for word in _title_keywords(title):
            lower = word.lower()

            if lower not in counts:
                order.append(lower)
                display[lower] = word

            counts[lower] = counts.get(lower, 0) + 1

    if not order:
        return next((title for title in titles if title), None)

    ranked = sorted(order, key=lambda word: (-counts[word], order.index(word)))
    top = ranked[:_LABEL_MAX_WORDS]
    top_in_appearance_order = sorted(top, key=order.index)

    label = " ".join(display[word] for word in top_in_appearance_order)

    return label[:1].upper() + label[1:]


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
    title_row = conn.execute(
        "SELECT title FROM articles WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    new_title = title_row[0] if title_row is not None else None

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
        label = derive_story_label([new_title] if new_title else [])

        cursor = conn.execute(
            """
            INSERT INTO stories (created_at, updated_at, article_count, label)
            VALUES (?, ?, 1, ?)
            """,
            (now, now, label),
        )
        story_id = cursor.lastrowid

        vector_store.upsert_story_centroid(conn, story_id, embedding)

    else:
        old_centroid = vector_store.get_story_centroid(conn, story_id)
        new_centroid = _running_mean(old_centroid, article_count, embedding)

        vector_store.upsert_story_centroid(conn, story_id, new_centroid)

        existing_titles = [
            row[0]
            for row in conn.execute(
                "SELECT title FROM articles WHERE story_id = ?",
                (story_id,),
            ).fetchall()
        ]
        label = derive_story_label(
            existing_titles + ([new_title] if new_title else [])
        )

        conn.execute(
            """
            UPDATE stories
            SET updated_at = ?, article_count = article_count + 1, label = ?
            WHERE story_id = ?
            """,
            (now, label, story_id),
        )

    conn.execute(
        "UPDATE articles SET story_id = ? WHERE article_id = ?",
        (story_id, article_id),
    )

    return story_id
