import os

import feedparser

from redis_queue import article_queue, redis_conn
from workers.worker import process_article


DEFAULT_RSS_FEEDS = [
    "https://www.theguardian.com/world/rss",
    "https://feeds.thelocal.com/rss/es",
    "https://www.upguard.com/breaches/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
]


def get_rss_feeds() -> list[str]:
    configured = os.getenv(
        "RSS_FEEDS",
        "",
    ).strip()

    if not configured:
        return DEFAULT_RSS_FEEDS

    return [
        url.strip()
        for url in configured.split(",")
        if url.strip()
    ]


def collect() -> None:
    max_entries = int(
        os.getenv(
            "MAX_ENTRIES_PER_FEED",
            "20",
        )
    )

    for feed_url in get_rss_feeds():
        print(
            f"Parsing {feed_url}",
            flush=True,
        )

        feed = feedparser.parse(feed_url)

        if getattr(feed, "bozo", False):
            error = getattr(
                feed,
                "bozo_exception",
                "unknown error",
            )

            print(
                f"Feed warning for {feed_url}: {error}",
                flush=True,
            )

        for entry in feed.entries[:max_entries]:
            url = getattr(entry, "link", None)
            title = getattr(entry, "title", url or "Untitled article")
            published = getattr(entry, "published", None)

            if not url:
                print(
                    f"Skipping entry without URL: {title}",
                    flush=True,
                )
                continue

            if redis_conn.sismember("seen_urls", url):
                print(
                    f"Already seen: {url}",
                    flush=True,
                )
                continue

            try:
                job = article_queue.enqueue(
                    process_article,
                    url,
                    title,
                    published,
                    job_timeout="10m",
                )

                redis_conn.sadd("seen_urls", url)

                print(
                    f"Enqueued {job.id}: {title}",
                    flush=True,
                )

            except Exception as exc:
                print(
                    f"Failed to enqueue {url}: {exc}",
                    flush=True,
                )


if __name__ == "__main__":
    collect()