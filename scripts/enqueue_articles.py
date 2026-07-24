"""Enqueue a hand-picked list of articles into the processing queue.

Reads URLs from positional arguments, one or more --file inputs, and/or
stdin, then enqueues them through the same path the RSS collector uses:
batched calls to process_article_batch, with URLs added to the Redis
`seen_urls` set only after RQ accepts each batch.

Each input line is `URL [optional title...]`. Lines that are blank or
start with `#` are ignored. If no title is given, the URL is used as the
title, matching the collector's default.

Examples:
    python enqueue_articles.py https://example.com/a https://example.com/b
    python enqueue_articles.py --file urls.txt
    cat urls.txt | python enqueue_articles.py --stdin
"""

import argparse
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path


def parse_line(line: str) -> dict | None:
    """Turn one input line into an article dict, or None to skip it."""
    stripped = line.strip()

    if not stripped or stripped.startswith("#"):
        return None

    # URLs contain no whitespace, so the first token is the URL and any
    # remainder is a human-friendly title.
    url, _, title = stripped.partition(" ")
    url = url.strip()
    title = title.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        print(
            f"Skipping line without an http(s) URL: {stripped!r}",
            file=sys.stderr,
            flush=True,
        )
        return None

    return {
        "url": url,
        "title": title or url,
        "published": None,
    }


def read_sources(
    urls: list[str],
    files: list[str],
    use_stdin: bool,
) -> Iterator[str]:
    yield from urls

    for file_path in files:
        text = Path(file_path).read_text(encoding="utf-8")
        yield from text.splitlines()

    if use_stdin:
        yield from sys.stdin.read().splitlines()


def dedupe_preserving_order(
    articles: Iterable[dict],
) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []

    for article in articles:
        url = article["url"]

        if url in seen:
            continue

        seen.add(url)
        unique.append(article)

    return unique


def batched(
    values: list[dict],
    size: int,
) -> Iterator[list[dict]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def enqueue_articles(
    articles: list[dict],
    force: bool,
) -> None:
    # Import heavy/connection-bound modules lazily so the parsing helpers
    # above stay importable and testable without Redis or spaCy present.
    from redis_queue import article_queue, redis_conn
    from workers.worker import MAX_BATCH_SIZE, process_article_batch

    if not force:
        fresh = [
            article
            for article in articles
            if not redis_conn.sismember("seen_urls", article["url"])
        ]

        skipped = len(articles) - len(fresh)

        if skipped:
            print(
                f"Skipping {skipped} URL(s) already in seen_urls",
                flush=True,
            )

        articles = fresh

    if not articles:
        print("Nothing to enqueue.", flush=True)
        return

    total_enqueued = 0

    for batch in batched(articles, size=MAX_BATCH_SIZE):
        job = article_queue.enqueue(
            process_article_batch,
            batch,
            job_timeout="20m",
            result_ttl=3600,
        )

        # Mark URLs only after Redis accepts the batch job, so a failed
        # enqueue does not permanently hide the article from re-runs.
        redis_conn.sadd(
            "seen_urls",
            *[article["url"] for article in batch],
        )

        total_enqueued += len(batch)

        print(
            f"Enqueued batch {job.id} with {len(batch)} article(s)",
            flush=True,
        )

    print(
        f"Done: {total_enqueued} article(s) enqueued.",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enqueue a manual list of articles for processing.",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="Article URLs given directly on the command line.",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Also read 'URL [title]' lines from standard input.",
    )
    parser.add_argument(
        "-f",
        "--file",
        action="append",
        default=[],
        dest="files",
        help="Path to a file of 'URL [title]' lines (repeatable).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Enqueue even if a URL is already in seen_urls.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print the articles without touching Redis.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.stdin and sys.stdin.isatty():
        print(
            "Reading URLs from stdin; press Ctrl-D when finished.",
            file=sys.stderr,
            flush=True,
        )

    raw_lines = read_sources(args.urls, args.files, args.stdin)

    articles = dedupe_preserving_order(
        article
        for article in (parse_line(line) for line in raw_lines)
        if article is not None
    )

    if not articles:
        print("No valid URLs found.", file=sys.stderr, flush=True)
        return 1

    if args.dry_run:
        print(f"Would enqueue {len(articles)} article(s):", flush=True)
        for article in articles:
            print(f"  {article['url']}  ({article['title']})", flush=True)
        return 0

    enqueue_articles(articles, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())