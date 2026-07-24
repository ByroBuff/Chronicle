"""Ingest a news site's sitemap into the processing queue.

Uses trafilatura's sitemap crawler (already a project dependency) to
discover article URLs, then enqueues them through the exact same path as
enqueue_articles.py / the RSS collector.

You can pass either a site homepage (the sitemap is discovered via
robots.txt) or a direct sitemap URL. Sitemap-index files are followed
automatically.

    python ingest_sitemap.py https://www.example-news.com
    python ingest_sitemap.py https://www.example-news.com/sitemap.xml
    python ingest_sitemap.py https://site.com --limit 200 --lang en
    python ingest_sitemap.py https://site.com --dry-run

Note: trafilatura's sitemap crawler returns URLs only. Your scraper
stores whatever title it is handed, and here that defaults to the URL,
so DB titles will equal the URL until the article is (re)scraped with
metadata extraction. See --help for --external and --max-sitemaps.
"""

import argparse
import sys

from scripts.enqueue_articles import dedupe_preserving_order, enqueue_articles


def discover_urls(
    site_url: str,
    lang: str | None,
    external: bool,
    max_sitemaps: int,
) -> list[str]:
    # Imported here so --help and import of this module do not require
    # trafilatura to be installed (it lives in the worker image).
    from trafilatura.sitemaps import sitemap_search

    return sitemap_search(
        site_url,
        target_lang=lang,
        external=external,
        max_sitemaps=max_sitemaps,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest a site's sitemap into the article queue.",
    )
    parser.add_argument(
        "site_url",
        help="Site homepage or a direct sitemap/sitemap-index URL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of URLs to enqueue (news sitemaps are big).",
    )
    parser.add_argument(
        "--lang",
        default=None,
        help="Restrict to a hreflang language code, e.g. 'en'.",
    )
    parser.add_argument(
        "--external",
        action="store_true",
        help="Allow URLs on domains other than the site's own.",
    )
    parser.add_argument(
        "--max-sitemaps",
        type=int,
        default=10000,
        help="Cap on sitemap files to traverse (default 10000).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Enqueue even if a URL is already in seen_urls.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List discovered URLs without enqueueing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    print(f"Discovering sitemap URLs for {args.site_url} ...", flush=True)

    try:
        urls = discover_urls(
            args.site_url,
            lang=args.lang,
            external=args.external,
            max_sitemaps=args.max_sitemaps,
        )
    except Exception as exc:
        print(f"Sitemap discovery failed: {exc}", file=sys.stderr, flush=True)
        return 1

    if not urls:
        print(
            "No URLs found. The site may block crawlers, expose no sitemap, "
            "or need --external. Try passing the sitemap URL directly.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    if args.limit is not None:
        urls = urls[: args.limit]

    articles = dedupe_preserving_order(
        {"url": url, "title": url, "published": None}
        for url in urls
    )

    print(f"Discovered {len(articles)} unique URL(s).", flush=True)

    if args.dry_run:
        for article in articles:
            print(f"  {article['url']}", flush=True)
        return 0

    enqueue_articles(articles, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())