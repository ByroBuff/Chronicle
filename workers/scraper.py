import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import aiohttp
import trafilatura


@dataclass(frozen=True)
class ArticleInput:
    url: str
    title: str
    published: str | None


@dataclass(frozen=True)
class ScrapedArticle:
    url: str
    title: str
    published: str | None
    clean_text: str
    language: str | None = None


def _normalize_published(raw: str | None) -> str | None:
    """Feeds hand back dates in whatever format they please (usually
    RFC 2822, sometimes ISO 8601). Normalize to a UTC ISO 8601 string so
    date-range search can compare published dates lexicographically;
    fall back to the raw value if it can't be parsed."""
    if not raw:
        return raw

    parsed: datetime | None

    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        parsed = None

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return raw

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc).isoformat()


async def fetch_html(
    session: aiohttp.ClientSession,
    article: ArticleInput,
) -> tuple[ArticleInput, str | None]:
    try:
        async with session.get(
            article.url,
            allow_redirects=True,
        ) as response:
            response.raise_for_status()

            html = await response.text(
                errors="replace"
            )

            return article, html

    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
    ) as exc:
        print(
            f"Fetch failed for {article.url}: {exc}",
            flush=True,
        )

        return article, None


def _resolve_title(article: ArticleInput, html: str) -> str:
    """Callers that don't know an article's real title (e.g. manual
    single-URL ingestion) pass the URL itself as a placeholder. Pull the
    page's actual title out of its HTML metadata in that case instead of
    keeping the URL as the displayed/translated title."""
    if article.title != article.url:
        return article.title

    try:
        metadata = trafilatura.extract_metadata(
            html,
            default_url=article.url,
        )
    except Exception:
        return article.title

    if metadata and metadata.title:
        return metadata.title

    return article.title


async def extract_article(
    article: ArticleInput,
    html: str | None,
) -> ScrapedArticle | None:
    if not html:
        return None

    try:
        clean_text = await asyncio.to_thread(
            trafilatura.extract,
            html,
            url=article.url,
            include_comments=False,
            include_tables=False,
        )

    except Exception as exc:
        print(
            f"Extraction failed for {article.url}: {exc}",
            flush=True,
        )

        return None

    if not clean_text:
        print(
            f"No article text extracted: {article.url}",
            flush=True,
        )

        return None

    title = await asyncio.to_thread(_resolve_title, article, html)

    return ScrapedArticle(
        url=article.url,
        title=title,
        published=_normalize_published(article.published),
        clean_text=clean_text,
    )


async def fetch_article_batch(
    articles: list[ArticleInput],
) -> list[ScrapedArticle]:
    timeout = aiohttp.ClientTimeout(
        total=45,
        connect=10,
    )

    connector = aiohttp.TCPConnector(
        limit=len(articles),
        limit_per_host=3,
    )

    headers = {
        "User-Agent": (
            "Chronicle/0.1 "
            "(RSS article aggregation service)"
        )
    }

    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers=headers,
    ) as session:
        fetched = await asyncio.gather(
            *[
                fetch_html(session, article)
                for article in articles
            ]
        )

        extracted = await asyncio.gather(
            *[
                extract_article(article, html)
                for article, html in fetched
            ]
        )

    return [
        article
        for article in extracted
        if article is not None
    ]