"""Similarity and story-clustering endpoints.

Reads embeddings/centroids that workers already computed via the shared
vec0 virtual tables (see top-level vector_store.py). This module never
loads the embedding model itself, so importing it stays cheap for the API
process, mirroring how api/observability.py avoids importing spaCy/DB deps.
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

import vector_store
from api.database import get_database
from api.queries import ARTICLE_SUMMARY_COLUMNS, ARTICLE_SUMMARY_JOIN
from api.models import (
    ArticleSummary,
    SimilarArticle,
    SimilarArticlesResponse,
    StoryDetail,
    StoryPage,
    StorySummary,
)


router = APIRouter(tags=["similarity"])


Database = Annotated[
    sqlite3.Connection,
    Depends(get_database),
]


def _article_exists(
    database: sqlite3.Connection,
    article_id: int,
) -> bool:
    return (
        database.execute(
            "SELECT 1 FROM articles WHERE article_id = ?",
            (article_id,),
        ).fetchone()
        is not None
    )


def _fetch_article_summaries(
    database: sqlite3.Connection,
    article_ids: list[int],
) -> dict[int, ArticleSummary]:
    if not article_ids:
        return {}

    placeholders = ", ".join("?" for _ in article_ids)

    rows = database.execute(
        f"""
        SELECT
            {ARTICLE_SUMMARY_COLUMNS}
        FROM articles
        {ARTICLE_SUMMARY_JOIN}
        WHERE articles.article_id IN ({placeholders})
        """,
        article_ids,
    ).fetchall()

    return {
        row["article_id"]: ArticleSummary(**dict(row))
        for row in rows
    }


@router.get(
    "/api/articles/{article_id}/similar",
    response_model=SimilarArticlesResponse,
)
def get_similar_articles(
    article_id: int,
    database: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> SimilarArticlesResponse:
    embedding = vector_store.get_article_embedding(database, article_id)

    if embedding is None:
        if not _article_exists(database, article_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article not found",
            )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article has no embedding yet",
        )

    neighbors = vector_store.find_similar_articles(
        database,
        embedding,
        limit=limit,
        exclude_article_id=article_id,
    )

    summaries = _fetch_article_summaries(
        database,
        [neighbor_id for neighbor_id, _ in neighbors],
    )

    items = [
        SimilarArticle(
            article_id=summaries[neighbor_id].article_id,
            url=summaries[neighbor_id].url,
            title=summaries[neighbor_id].title,
            published=summaries[neighbor_id].published,
            excerpt=summaries[neighbor_id].excerpt,
            similarity=round(1.0 - distance, 4),
        )
        for neighbor_id, distance in neighbors
        if neighbor_id in summaries
    ]

    return SimilarArticlesResponse(
        article_id=article_id,
        items=items,
    )


@router.get(
    "/api/articles/{article_id}/story",
    response_model=StoryDetail,
)
def get_article_story(
    article_id: int,
    database: Database,
) -> StoryDetail:
    row = database.execute(
        """
        SELECT
            articles.story_id,
            stories.article_count
        FROM articles
        LEFT JOIN stories
            ON stories.story_id = articles.story_id
        WHERE articles.article_id = ?
        """,
        (article_id,),
    ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    # A story only becomes a real, browsable story once a second article
    # joins it — a lone article "story" is just clustering bookkeeping.
    if row["story_id"] is None or (row["article_count"] or 0) <= 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article is not part of a story yet",
        )

    return get_story(row["story_id"], database)


@router.get(
    "/api/stories",
    response_model=StoryPage,
)
def list_stories(
    database: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StoryPage:
    # A story only counts once a second article has joined it — a lone
    # article "story" is just clustering bookkeeping, not a real story.
    total = database.execute(
        "SELECT COUNT(*) FROM stories WHERE article_count > 1"
    ).fetchone()[0]

    rows = database.execute(
        """
        SELECT story_id, created_at, updated_at, article_count, label
        FROM stories
        WHERE article_count > 1
        ORDER BY updated_at DESC
        LIMIT ?
        OFFSET ?
        """,
        (limit, offset),
    ).fetchall()

    return StoryPage(
        items=[
            StorySummary(**dict(row))
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/stories/{story_id}",
    response_model=StoryDetail,
)
def get_story(
    story_id: int,
    database: Database,
) -> StoryDetail:
    story = database.execute(
        """
        SELECT story_id, created_at, updated_at, article_count, label
        FROM stories
        WHERE story_id = ?
          AND article_count > 1
        """,
        (story_id,),
    ).fetchone()

    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found",
        )

    rows = database.execute(
        f"""
        SELECT
            {ARTICLE_SUMMARY_COLUMNS}
        FROM articles
        {ARTICLE_SUMMARY_JOIN}
        WHERE articles.story_id = ?
        ORDER BY articles.article_id DESC
        """,
        (story_id,),
    ).fetchall()

    return StoryDetail(
        **dict(story),
        articles=[
            ArticleSummary(**dict(row))
            for row in rows
        ],
    )


@router.get(
    "/api/stories/{story_id}/articles",
    response_model=list[ArticleSummary],
)
def list_story_articles(
    story_id: int,
    database: Database,
) -> list[ArticleSummary]:
    story_exists = database.execute(
        "SELECT 1 FROM stories WHERE story_id = ? AND article_count > 1",
        (story_id,),
    ).fetchone()

    if story_exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found",
        )

    rows = database.execute(
        f"""
        SELECT
            {ARTICLE_SUMMARY_COLUMNS}
        FROM articles
        {ARTICLE_SUMMARY_JOIN}
        WHERE articles.story_id = ?
        ORDER BY articles.article_id DESC
        """,
        (story_id,),
    ).fetchall()

    return [
        ArticleSummary(**dict(row))
        for row in rows
    ]
