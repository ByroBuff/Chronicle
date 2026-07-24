"""Observability endpoints for the pipeline dashboard.

Throughput and totals come from the Redis metrics stream/counters that
workers emit (see top-level metrics.py). Worker and queue liveness come
from RQ's own registries. Nothing here touches SQLite.
"""

import os
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from redis import Redis
from rq import Queue, Worker
from rq.registry import (
    FailedJobRegistry,
    FinishedJobRegistry,
    StartedJobRegistry,
)

import metrics


QUEUE_NAME = os.getenv("RQ_QUEUE", "article_processing")

# RQ manages its own byte encoding, so this connection must NOT decode.
_rq_redis = Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    db=int(os.getenv("REDIS_DB", "0")),
    decode_responses=False,
)


router = APIRouter(prefix="/api/metrics", tags=["metrics"])


# --- Response models ------------------------------------------------------


class Totals(BaseModel):
    received: int
    scraped: int
    ingested: int
    batches: int
    avg_batch_seconds: float
    scrape_success_rate: float
    ingest_rate: float


class Throughput(BaseModel):
    window_seconds: float
    received_per_second: float
    scraped_per_second: float
    ingested_per_second: float
    batches_per_second: float
    avg_batch_seconds: float
    totals_in_window: dict


class WorkerInfo(BaseModel):
    name: str
    state: str
    current_job_id: str | None
    successful_jobs: int
    failed_jobs: int
    working_time_seconds: float
    heartbeat_age_seconds: float | None
    queues: list[str]


class WorkerSummary(BaseModel):
    total: int
    busy: int
    idle: int
    workers: list[WorkerInfo]


class QueueStatus(BaseModel):
    queue: str
    queued: int
    started: int
    finished: int
    failed: int


class MetricsSnapshot(BaseModel):
    generated_at: str
    totals: Totals
    throughput: Throughput
    queue: QueueStatus
    workers: WorkerSummary


# --- Builders -------------------------------------------------------------


def _throughput(window_seconds: float) -> Throughput:
    events = metrics.read_window(window_seconds)
    return Throughput(**metrics.compute_rates(events, window_seconds))


def _queue_status() -> QueueStatus:
    queue = Queue(QUEUE_NAME, connection=_rq_redis)

    return QueueStatus(
        queue=QUEUE_NAME,
        queued=queue.count,
        started=StartedJobRegistry(queue=queue).count,
        finished=FinishedJobRegistry(queue=queue).count,
        failed=FailedJobRegistry(queue=queue).count,
    )


def _worker_summary() -> WorkerSummary:
    now = datetime.now(timezone.utc)
    workers = Worker.all(connection=_rq_redis)

    infos: list[WorkerInfo] = []
    busy = 0

    for worker in workers:
        # Only count workers attached to our queue.
        queue_names = worker.queue_names()

        if QUEUE_NAME not in queue_names:
            continue

        state = worker.get_state()

        if state == "busy":
            busy += 1

        heartbeat = worker.last_heartbeat
        heartbeat_age = None

        if heartbeat is not None:
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            heartbeat_age = round((now - heartbeat).total_seconds(), 1)

        infos.append(
            WorkerInfo(
                name=worker.name,
                state=state,
                current_job_id=worker.get_current_job_id(),
                successful_jobs=worker.successful_job_count,
                failed_jobs=worker.failed_job_count,
                working_time_seconds=round(worker.total_working_time, 1),
                heartbeat_age_seconds=heartbeat_age,
                queues=queue_names,
            )
        )

    return WorkerSummary(
        total=len(infos),
        busy=busy,
        idle=len(infos) - busy,
        workers=infos,
    )


# --- Routes ---------------------------------------------------------------


@router.get("/totals", response_model=Totals)
def totals() -> Totals:
    return Totals(**metrics.read_totals())


@router.get("/throughput", response_model=Throughput)
def throughput(
    window: Annotated[float, Query(ge=1, le=86400)] = 60,
) -> Throughput:
    return _throughput(window)


@router.get("/timeseries")
def timeseries(
    window: Annotated[float, Query(ge=1, le=86400)] = 300,
    bucket: Annotated[float, Query(ge=1, le=3600)] = 10,
) -> dict:
    events = metrics.read_window(window)

    return {
        "window_seconds": window,
        "bucket_seconds": bucket,
        "series": metrics.bucketize(events, window, bucket),
    }


@router.get("/workers", response_model=WorkerSummary)
def workers() -> WorkerSummary:
    return _worker_summary()


@router.get("/queue", response_model=QueueStatus)
def queue_status() -> QueueStatus:
    return _queue_status()


@router.get("", response_model=MetricsSnapshot)
def snapshot(
    window: Annotated[float, Query(ge=1, le=86400)] = 60,
) -> MetricsSnapshot:
    """One-shot snapshot for a dashboard poll."""
    return MetricsSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        totals=Totals(**metrics.read_totals()),
        throughput=_throughput(window),
        queue=_queue_status(),
        workers=_worker_summary(),
    )