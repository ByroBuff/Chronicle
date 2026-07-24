"""Pipeline metrics backed by Redis.

Workers emit one event per processed batch (a Redis Stream entry) plus
cumulative counters. The API reads the stream over a time window to
derive per-second rates and time series, and reads the counters for
all-time totals. Worker/queue liveness is read separately from RQ.

Kept dependency-light (redis only) so both the worker and the API can
import it without pulling in spaCy or the DB layer.
"""

import math
import os
import time

from redis import Redis


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# Per-batch event stream. Entry IDs are millisecond timestamps, which we
# reuse for time-window queries instead of storing a separate timestamp.
STREAM_KEY = "metrics:batches"

# Roughly cap the stream so it cannot grow without bound. At a few batches
# per second this retains many hours of history; the API only ever reads a
# recent window, and the totals below cover all-time numbers.
STREAM_MAXLEN = 200_000

TOTAL_RECEIVED = "metrics:total:received"
TOTAL_SCRAPED = "metrics:total:scraped"
TOTAL_INGESTED = "metrics:total:ingested"
TOTAL_BATCHES = "metrics:total:batches"
TOTAL_DURATION_MS = "metrics:total:duration_ms"

_TOTAL_KEYS = (
    TOTAL_RECEIVED,
    TOTAL_SCRAPED,
    TOTAL_INGESTED,
    TOTAL_BATCHES,
    TOTAL_DURATION_MS,
)


_redis: Redis | None = None


def get_redis() -> Redis:
    """Lazily create a decode_responses client shared across calls."""
    global _redis

    if _redis is None:
        _redis = Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
        )

    return _redis


def record_batch(
    received: int,
    scraped: int,
    ingested: int,
    duration_seconds: float,
) -> None:
    """Emit one batch event. Never raises into the caller's job."""
    duration_ms = int(duration_seconds * 1000)

    try:
        conn = get_redis()
        pipe = conn.pipeline()

        pipe.xadd(
            STREAM_KEY,
            {
                "received": received,
                "scraped": scraped,
                "ingested": ingested,
                "duration_ms": duration_ms,
            },
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )

        pipe.incrby(TOTAL_RECEIVED, received)
        pipe.incrby(TOTAL_SCRAPED, scraped)
        pipe.incrby(TOTAL_INGESTED, ingested)
        pipe.incrby(TOTAL_BATCHES, 1)
        pipe.incrby(TOTAL_DURATION_MS, duration_ms)

        pipe.execute()

    except Exception as exc:
        # Metrics must never take down ingestion.
        print(f"metrics: failed to record batch: {exc}", flush=True)


def read_window(window_seconds: float) -> list[dict]:
    """Return batch events from the last `window_seconds`, oldest first."""
    conn = get_redis()

    start_ms = int((time.time() - window_seconds) * 1000)

    raw = conn.xrange(STREAM_KEY, min=start_ms, max="+")

    events: list[dict] = []

    for entry_id, fields in raw:
        # Entry id looks like "1712345678901-0"; the first part is ms.
        ts_ms = int(entry_id.split("-")[0])

        events.append(
            {
                "ts_ms": ts_ms,
                "received": int(fields.get("received", 0)),
                "scraped": int(fields.get("scraped", 0)),
                "ingested": int(fields.get("ingested", 0)),
                "duration_ms": int(fields.get("duration_ms", 0)),
            }
        )

    return events


def read_totals() -> dict:
    conn = get_redis()

    values = conn.mget(_TOTAL_KEYS)
    numbers = [int(value) if value is not None else 0 for value in values]

    (
        received,
        scraped,
        ingested,
        batches,
        duration_ms,
    ) = numbers

    avg_batch_ms = (duration_ms / batches) if batches else 0.0

    return {
        "received": received,
        "scraped": scraped,
        "ingested": ingested,
        "batches": batches,
        "avg_batch_seconds": round(avg_batch_ms / 1000, 4),
        "scrape_success_rate": round(scraped / received, 4) if received else 0.0,
        "ingest_rate": round(ingested / scraped, 4) if scraped else 0.0,
    }


# --- Pure aggregation helpers (no I/O; unit-testable) ---------------------


def aggregate(events: list[dict]) -> dict:
    return {
        "received": sum(e["received"] for e in events),
        "scraped": sum(e["scraped"] for e in events),
        "ingested": sum(e["ingested"] for e in events),
        "duration_ms": sum(e["duration_ms"] for e in events),
        "batches": len(events),
    }


def compute_rates(events: list[dict], window_seconds: float) -> dict:
    sums = aggregate(events)
    window = window_seconds or 1.0

    return {
        "window_seconds": window_seconds,
        "received_per_second": round(sums["received"] / window, 3),
        "scraped_per_second": round(sums["scraped"] / window, 3),
        "ingested_per_second": round(sums["ingested"] / window, 3),
        "batches_per_second": round(sums["batches"] / window, 3),
        "avg_batch_seconds": round(
            (sums["duration_ms"] / sums["batches"] / 1000), 4
        )
        if sums["batches"]
        else 0.0,
        "totals_in_window": {
            "received": sums["received"],
            "scraped": sums["scraped"],
            "ingested": sums["ingested"],
            "batches": sums["batches"],
        },
    }


def bucketize(
    events: list[dict],
    window_seconds: float,
    bucket_seconds: float,
    now_ms: int | None = None,
) -> list[dict]:
    """Group events into fixed-width time buckets for charting.

    Returns oldest-first buckets, each with summed counts and the
    per-second rate within that bucket. Empty buckets are included so a
    dashboard gets an evenly spaced series.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)

    bucket_ms = int(bucket_seconds * 1000)
    bucket_count = max(1, math.ceil(window_seconds / bucket_seconds))

    window_start_ms = now_ms - bucket_count * bucket_ms

    buckets = [
        {
            "received": 0,
            "scraped": 0,
            "ingested": 0,
            "batches": 0,
        }
        for _ in range(bucket_count)
    ]

    for event in events:
        offset_ms = event["ts_ms"] - window_start_ms

        if offset_ms < 0:
            continue

        index = int(offset_ms // bucket_ms)

        if index >= bucket_count:
            index = bucket_count - 1

        bucket = buckets[index]
        bucket["received"] += event["received"]
        bucket["scraped"] += event["scraped"]
        bucket["ingested"] += event["ingested"]
        bucket["batches"] += 1

    series = []

    for index, bucket in enumerate(buckets):
        start_ms = window_start_ms + index * bucket_ms

        series.append(
            {
                "bucket_start_ms": start_ms,
                "received": bucket["received"],
                "scraped": bucket["scraped"],
                "ingested": bucket["ingested"],
                "batches": bucket["batches"],
                "scraped_per_second": round(
                    bucket["scraped"] / bucket_seconds, 3
                ),
                "ingested_per_second": round(
                    bucket["ingested"] / bucket_seconds, 3
                ),
            }
        )

    return series