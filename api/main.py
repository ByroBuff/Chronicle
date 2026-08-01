import os
import sqlite3
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from starlette.responses import Response

from api.database import get_database
from api.ingest import router as ingest_router
from api.queries import ARTICLE_SUMMARY_COLUMNS, ARTICLE_SUMMARY_JOIN
from api.models import (
    ArticleDetail,
    ArticlePage,
    ArticleStats,
    ArticleSummary,
    EntityPage,
    EntitySummary,
)
from api.observability import router as metrics_router
from api.similarity import router as similarity_router


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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


app.include_router(metrics_router)
app.include_router(similarity_router)
app.include_router(ingest_router)


# Serve the ops dashboard same-origin so its fetches to /api/* need no CORS.
_static_dir = os.path.join(os.path.dirname(__file__), "static")


class NoCacheStaticFiles(StaticFiles):
    """Force browsers to revalidate on every request instead of trusting a
    heuristic freshness lifetime, so a redeployed dashboard is never served
    from a stale cached copy of an old, incompatible index.html/app.js pair.
    """

    def file_response(self, *args: object, **kwargs: object) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Registered before the StaticFiles mount below: Starlette's router takes
# the first matching route, and a Mount claims its whole prefix, so this
# explicit route must come first for the SPA-style article page to win
# over "file not found" from the static handler.
@app.get(
    "/dashboard/article/{article_id}",
    include_in_schema=False,
)
def dashboard_article_page(article_id: int) -> FileResponse:
    return FileResponse(
        os.path.join(_static_dir, "article.html"),
        headers={"Cache-Control": "no-cache"},
    )


@app.get(
    "/dashboard/story/{story_id}",
    include_in_schema=False,
)
def dashboard_story_page(story_id: int) -> FileResponse:
    return FileResponse(
        os.path.join(_static_dir, "story.html"),
        headers={"Cache-Control": "no-cache"},
    )


@app.get(
    "/dashboard/entity/{entity_id}",
    include_in_schema=False,
)
def dashboard_entity_page(entity_id: int) -> FileResponse:
    return FileResponse(
        os.path.join(_static_dir, "entity.html"),
        headers={"Cache-Control": "no-cache"},
    )


@app.get(
    "/dashboard/search",
    include_in_schema=False,
)
def dashboard_search_page() -> FileResponse:
    return FileResponse(
        os.path.join(_static_dir, "search.html"),
        headers={"Cache-Control": "no-cache"},
    )


app.mount(
    "/dashboard",
    NoCacheStaticFiles(directory=_static_dir, html=True),
    name="dashboard",
)


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


def _exclusive_upper_bound(date_value: str) -> str:
    """Turn a plain YYYY-MM-DD date into the start of the following day,
    so a date_to filter includes every timestamp on that day. Values that
    aren't a bare date (e.g. already a full timestamp) pass through
    unchanged and are compared as-is."""
    try:
        parsed = datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        return date_value

    return (parsed + timedelta(days=1)).strftime("%Y-%m-%d")


def _domain_url_patterns(domain: str) -> list[str]:
    cleaned = (
        domain.strip()
        .lower()
        .removeprefix("http://")
        .removeprefix("https://")
        .removeprefix("www.")
        .split("/")[0]
    )

    return [
        f"%://{cleaned}",
        f"%://{cleaned}/%",
        f"%://www.{cleaned}",
        f"%://www.{cleaned}/%",
    ]


@app.get(
    "/api/articles",
    response_model=ArticlePage,
)
def list_articles(
    database: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    query: Annotated[str | None, Query(alias="q")] = None,
    title: Annotated[str | None, Query()] = None,
    text: Annotated[str | None, Query()] = None,
    domain: Annotated[str | None, Query()] = None,
    language: Annotated[str | None, Query()] = None,
    date_from: Annotated[str | None, Query()] = None,
    date_to: Annotated[str | None, Query()] = None,
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

    if title:
        conditions.append("articles.title LIKE ?")
        parameters.append(f"%{title.strip()}%")

    if text:
        conditions.append("articles.clean_text LIKE ?")
        parameters.append(f"%{text.strip()}%")

    if language:
        conditions.append("articles.language = ?")
        parameters.append(language.strip().lower())

    if domain:
        patterns = _domain_url_patterns(domain)

        conditions.append(
            "(" + " OR ".join(["articles.url LIKE ?"] * len(patterns)) + ")"
        )
        parameters.extend(patterns)

    if date_from:
        conditions.append("articles.published >= ?")
        parameters.append(date_from.strip())

    if date_to:
        conditions.append("articles.published < ?")
        parameters.append(_exclusive_upper_bound(date_to.strip()))

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
            {ARTICLE_SUMMARY_COLUMNS}
        FROM articles
        {ARTICLE_SUMMARY_JOIN}
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
            articles.article_id,
            articles.url,
            articles.title,
            articles.published,
            articles.clean_text,
            articles.language,
            CASE
                WHEN stories.article_count > 1 THEN articles.story_id
                ELSE NULL
            END AS story_id
        FROM articles
        LEFT JOIN stories
            ON stories.story_id = articles.story_id
        WHERE articles.article_id = ?
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
    "/api/entities/{entity_id}",
    response_model=EntitySummary,
)
def get_entity(
    entity_id: int,
    database: Database,
) -> EntitySummary:
    row = database.execute(
        """
        SELECT
            entities.entity_id,
            entities.entity_type,
            entities.canonical_name,
            COUNT(article_entities.article_id) AS article_count
        FROM entities
        LEFT JOIN article_entities
            ON article_entities.entity_id = entities.entity_id
        WHERE entities.entity_id = ?
        GROUP BY entities.entity_id
        """,
        (entity_id,),
    ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entity not found",
        )

    return EntitySummary(**dict(row))


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
        f"""
        SELECT
            {ARTICLE_SUMMARY_COLUMNS}
        FROM articles
        INNER JOIN article_entities
            ON article_entities.article_id = articles.article_id
        {ARTICLE_SUMMARY_JOIN}
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