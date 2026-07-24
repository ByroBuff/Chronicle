import asyncio
from dataclasses import dataclass

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

    return ScrapedArticle(
        url=article.url,
        title=article.title,
        published=article.published,
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