import time

import feedparser

from collector.feed_config import FeedConfig, load_feeds
from redis_queue import article_queue, redis_conn
from workers.worker import process_article


def get_last_polled(feed: FeedConfig) -> int | None:
    value = redis_conn.get(
        f"feed:last_polled:{feed.feed_id}"
    )

    if value is None:
        return None

    return int(value)


def is_feed_due(
    feed: FeedConfig,
    current_time: int,
) -> bool:
    last_polled = get_last_polled(feed)

    if last_polled is None:
        return True

    elapsed = current_time - last_polled

    return elapsed >= feed.poll_interval_seconds


def collect_feed(feed: FeedConfig) -> None:
    current_time = int(time.time())

    if not is_feed_due(feed, current_time):
        last_polled = get_last_polled(feed)

        if last_polled is not None:
            remaining = max(
                0,
                feed.poll_interval_seconds
                - (current_time - last_polled),
            )

            print(
                f"Skipping {feed.name}; "
                f"next poll in {remaining} seconds",
                flush=True,
            )

        return

    lock_key = f"feed:lock:{feed.feed_id}"

    lock_acquired = redis_conn.set(
        lock_key,
        "1",
        nx=True,
        ex=300,
    )

    if not lock_acquired:
        print(
            f"Skipping {feed.name}; another collector owns the lock",
            flush=True,
        )
        return

    try:
        print(
            f"Parsing {feed.name}: {feed.url}",
            flush=True,
        )

        parsed_feed = feedparser.parse(feed.url)

        entry_count = len(parsed_feed.entries)

        print(
            f"{feed.name} returned {entry_count} entries",
            flush=True,
        )

        if getattr(parsed_feed, "bozo", False):
            error = getattr(
                parsed_feed,
                "bozo_exception",
                "unknown parsing error",
            )

            print(
                f"Feed warning for {feed.name}: {error}",
                flush=True,
            )

            # Do not record a successful poll when the feed returned
            # no usable entries.
            if not parsed_feed.entries:
                return

        enqueued = 0
        previously_seen = 0
        skipped = 0

        for entry in parsed_feed.entries[:feed.max_entries]:
            url = getattr(entry, "link", None)

            if not url:
                skipped += 1
                continue

            title = getattr(
                entry,
                "title",
                url,
            )

            published = getattr(
                entry,
                "published",
                None,
            )

            if redis_conn.sismember("seen_urls", url):
                previously_seen += 1
                continue

            try:
                job = article_queue.enqueue(
                    process_article,
                    url,
                    title,
                    published,
                    job_timeout="10m",
                )

                # Only mark the URL after RQ accepts the job.
                redis_conn.sadd(
                    "seen_urls",
                    url,
                )

                enqueued += 1

                print(f"Enqueued {job.id} from {feed.name}: {title}", flush=True)

            except Exception as exc:
                print(f"Failed to enqueue {url}: {exc}", flush=True)

        redis_conn.set(f"feed:last_polled:{feed.feed_id}", current_time)

        print(
            f"Completed {feed.name}: "
            f"{enqueued} enqueued, "
            f"{previously_seen} already seen, "
            f"{skipped} skipped",
            flush=True,
        )

    finally:
        redis_conn.delete(lock_key)


def collect() -> None:
    feeds = load_feeds()

    enabled_feeds = [
        feed
        for feed in feeds
        if feed.enabled
    ]

    print(
        f"Loaded {len(enabled_feeds)} enabled feeds "
        f"out of {len(feeds)} configured feeds",
        flush=True,
    )

    for feed in enabled_feeds:
        try:
            collect_feed(feed)
        except Exception as exc:
            print(
                f"Collection failed for {feed.name}: {exc}",
                flush=True,
            )


if __name__ == "__main__":
    collect()