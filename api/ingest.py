"""Synchronous single-URL ingestion for the dashboard's "paste a URL" box.

Unlike the collector/worker pipeline (which enqueues batches through RQ and
processes them out-of-band), this endpoint scrapes, translates, extracts
entities, embeds, and clusters a single article inline and hands back its
article_id directly. That is a deliberate trade-off: the API process now
loads the same heavy models (spaCy, fastembed, Argos Translate) as the
worker, and a request can take several seconds. In exchange the dashboard
can redirect straight to /dashboard/article/{id} instead of polling a job.
"""

import asyncio
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.database import get_database
from api.models import IngestRequest, IngestResponse
from workers.worker import (
    embed_and_cluster_batch,
    insert_batch,
    process_batch_async,
)


router = APIRouter(tags=["ingest"])


Database = Annotated[
    sqlite3.Connection,
    Depends(get_database),
]


@router.post(
    "/api/ingest",
    response_model=IngestResponse,
)
async def ingest_url(
    payload: IngestRequest,
    database: Database,
    response: Response,
) -> IngestResponse:
    url = payload.url.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="url must start with http:// or https://",
        )

    existing = database.execute(
        "SELECT article_id FROM articles WHERE url = ?",
        (url,),
    ).fetchone()

    if existing is not None:
        response.status_code = status.HTTP_200_OK

        return IngestResponse(
            article_id=existing["article_id"],
            url=url,
            created=False,
        )

    article_data = [
        {
            "url": url,
            "title": payload.title or url,
            "published": None,
        }
    ]

    processed_articles = await process_batch_async(article_data)

    if not processed_articles:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not fetch or extract article text from that URL",
        )

    # insert_batch/embed_and_cluster_batch are blocking (SQLite + ONNX
    # inference), so keep them off the event loop.
    inserted = await asyncio.to_thread(insert_batch, processed_articles)

    if not inserted:
        # Another request or worker inserted the same URL concurrently.
        row = database.execute(
            "SELECT article_id FROM articles WHERE url = ?",
            (url,),
        ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Article insert raced and could not be recovered",
            )

        response.status_code = status.HTTP_200_OK

        return IngestResponse(
            article_id=row["article_id"],
            url=url,
            created=False,
        )

    await asyncio.to_thread(embed_and_cluster_batch, inserted)

    article_id, _ = inserted[0]

    response.status_code = status.HTTP_201_CREATED

    return IngestResponse(
        article_id=article_id,
        url=url,
        created=True,
    )
