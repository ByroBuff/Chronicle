import os
import sqlite3
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from api.database import get_database
from api.models import (
    ArticleDetail,
    ArticlePage,
    ArticleStats,
    ArticleSummary,
    EntityPage,
    EntitySummary,
)
from api.observability import router as metrics_router


app = FastAPI(
    title="Chronicle API",
    version="0.1.0",
    description="API for collected articles and extracted entities.",
)


cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173",
    ).split(",")
    if origin.strip()
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


app.include_router(metrics_router)


Database = Annotated[
    sqlite3.Connection,
    Depends(get_database),
]


@app.get("/health")
def health(database: Database) -> dict:
    try:
        database.execute("SELECT 1").fetchone()

        article_count = database.execute(
            "SELECT COUNT(*) FROM articles"
        ).fetchone()[0]

        return {
            "status": "ok",
            "database": "connected",
            "articles": article_count,
        }

    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unavailable: {exc}",
        ) from exc


@app.get(
    "/api/articles",
    response_model=ArticlePage,
)
def list_articles(
    database: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    query: Annotated[str | None, Query(alias="q")] = None,
) -> ArticlePage:
    conditions: list[str] = []
    parameters: list[object] = []

    if query:
        search_value = f"%{query.strip()}%"

        conditions.append(
            """
            (
                articles.title LIKE ?
                OR articles.clean_text LIKE ?
            )
            """
        )

        parameters.extend(
            [
                search_value,
                search_value,
            ]
        )

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    total = database.execute(
        f"""
        SELECT COUNT(*)
        FROM articles
        {where_clause}
        """,
        parameters,
    ).fetchone()[0]

    rows = database.execute(
        f"""
        SELECT
            article_id,
            url,
            title,
            published,
            SUBSTR(
                REPLACE(clean_text, CHAR(10), ' '),
                1,
                300
            ) AS excerpt
        FROM articles
        {where_clause}
        ORDER BY article_id DESC
        LIMIT ?
        OFFSET ?
        """,
        [
            *parameters,
            limit,
            offset,
        ],
    ).fetchall()

    return ArticlePage(
        items=[
            ArticleSummary(**dict(row))
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/api/articles/{article_id}",
    response_model=ArticleDetail,
)
def get_article(
    article_id: int,
    database: Database,
) -> ArticleDetail:
    article = database.execute(
        """
        SELECT
            article_id,
            url,
            title,
            published,
            clean_text
        FROM articles
        WHERE article_id = ?
        """,
        (article_id,),
    ).fetchone()

    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    entity_rows = database.execute(
        """
        SELECT
            entities.entity_id,
            entities.entity_type,
            entities.canonical_name
        FROM entities
        INNER JOIN article_entities
            ON article_entities.entity_id = entities.entity_id
        WHERE article_entities.article_id = ?
        ORDER BY
            entities.entity_type,
            entities.canonical_name
        """,
        (article_id,),
    ).fetchall()

    return ArticleDetail(
        **dict(article),
        entities=[
            EntitySummary(**dict(row))
            for row in entity_rows
        ],
    )


@app.get(
    "/api/entities",
    response_model=EntityPage,
)
def list_entities(
    database: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    entity_type: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query(alias="q")] = None,
) -> EntityPage:
    conditions: list[str] = []
    parameters: list[object] = []

    if entity_type:
        conditions.append("entities.entity_type = ?")
        parameters.append(entity_type.upper())

    if query:
        conditions.append("entities.canonical_name LIKE ?")
        parameters.append(f"%{query.strip()}%")

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    total = database.execute(
        f"""
        SELECT COUNT(*)
        FROM entities
        {where_clause}
        """,
        parameters,
    ).fetchone()[0]

    rows = database.execute(
        f"""
        SELECT
            entities.entity_id,
            entities.entity_type,
            entities.canonical_name,
            COUNT(article_entities.article_id) AS article_count
        FROM entities
        LEFT JOIN article_entities
            ON article_entities.entity_id = entities.entity_id
        {where_clause}
        GROUP BY entities.entity_id
        ORDER BY
            article_count DESC,
            entities.canonical_name ASC
        LIMIT ?
        OFFSET ?
        """,
        [
            *parameters,
            limit,
            offset,
        ],
    ).fetchall()

    return EntityPage(
        items=[
            EntitySummary(**dict(row))
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/api/entities/{entity_id}/articles",
    response_model=ArticlePage,
)
def list_entity_articles(
    entity_id: int,
    database: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ArticlePage:
    entity_exists = database.execute(
        """
        SELECT 1
        FROM entities
        WHERE entity_id = ?
        """,
        (entity_id,),
    ).fetchone()

    if entity_exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entity not found",
        )

    total = database.execute(
        """
        SELECT COUNT(*)
        FROM article_entities
        WHERE entity_id = ?
        """,
        (entity_id,),
    ).fetchone()[0]

    rows = database.execute(
        """
        SELECT
            articles.article_id,
            articles.url,
            articles.title,
            articles.published,
            SUBSTR(
                REPLACE(articles.clean_text, CHAR(10), ' '),
                1,
                300
            ) AS excerpt
        FROM articles
        INNER JOIN article_entities
            ON article_entities.article_id = articles.article_id
        WHERE article_entities.entity_id = ?
        ORDER BY articles.article_id DESC
        LIMIT ?
        OFFSET ?
        """,
        (
            entity_id,
            limit,
            offset,
        ),
    ).fetchall()

    return ArticlePage(
        items=[
            ArticleSummary(**dict(row))
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/api/stats",
    response_model=ArticleStats,
)
def get_stats(database: Database) -> ArticleStats:
    articles = database.execute(
        "SELECT COUNT(*) FROM articles"
    ).fetchone()[0]

    entities = database.execute(
        "SELECT COUNT(*) FROM entities"
    ).fetchone()[0]

    people = database.execute(
        """
        SELECT COUNT(*)
        FROM entities
        WHERE entity_type = 'PERSON'
        """
    ).fetchone()[0]

    locations = database.execute(
        """
        SELECT COUNT(*)
        FROM entities
        WHERE entity_type = 'LOCATION'
        """
    ).fetchone()[0]

    return ArticleStats(
        articles=articles,
        entities=entities,
        people=people,
        locations=locations,
    )