from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import tomllib


FEED_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class FeedConfig:
    feed_id: str
    name: str
    url: str

    enabled: bool = True
    category: str = "general"
    max_entries: int = 20
    poll_interval_seconds: int = 900
    tags: list[str] = field(default_factory=list)


def load_feeds() -> list[FeedConfig]:
    config_path = Path(
        os.getenv(
            "FEEDS_CONFIG_PATH",
            "config/feeds.toml",
        )
    )

    if not config_path.exists():
        raise FileNotFoundError(
            f"Feed configuration does not exist: {config_path}"
        )

    with config_path.open("rb") as file:
        config = tomllib.load(file)

    raw_feeds = config.get("feeds", [])

    feeds: list[FeedConfig] = []
    feed_ids: set[str] = set()
    feed_urls: set[str] = set()

    for index, raw_feed in enumerate(raw_feeds, start=1):
        try:
            feed_id = str(raw_feed["id"]).strip()
            name = str(raw_feed["name"]).strip()
            url = str(raw_feed["url"]).strip()
        except KeyError as exc:
            raise ValueError(
                f"Feed #{index} is missing required field: {exc.args[0]}"
            ) from exc

        if not FEED_ID_PATTERN.fullmatch(feed_id):
            raise ValueError(
                f"Invalid feed ID {feed_id!r}. "
                "Use lowercase letters, numbers, hyphens, and underscores."
            )

        if feed_id in feed_ids:
            raise ValueError(
                f"Duplicate feed ID: {feed_id}"
            )

        if url in feed_urls:
            raise ValueError(
                f"Duplicate feed URL: {url}"
            )

        max_entries = int(
            raw_feed.get(
                "max_entries",
                20,
            )
        )

        poll_interval = int(
            raw_feed.get(
                "poll_interval_seconds",
                900,
            )
        )

        if max_entries < 1:
            raise ValueError(
                f"{feed_id}: max_entries must be at least 1"
            )

        if poll_interval < 60:
            raise ValueError(
                f"{feed_id}: poll_interval_seconds must be at least 60"
            )

        tags = [
            str(tag).strip()
            for tag in raw_feed.get("tags", [])
            if str(tag).strip()
        ]

        feeds.append(
            FeedConfig(
                feed_id=feed_id,
                name=name,
                url=url,
                enabled=bool(
                    raw_feed.get(
                        "enabled",
                        True,
                    )
                ),
                category=str(
                    raw_feed.get(
                        "category",
                        "general",
                    )
                ).strip(),
                max_entries=max_entries,
                poll_interval_seconds=poll_interval,
                tags=tags,
            )
        )

        feed_ids.add(feed_id)
        feed_urls.add(url)

    return feeds