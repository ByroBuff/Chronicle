import feedparser
from redis import Redis
from rq import Queue

from workers.worker import process_article

RSS_FEEDS = [
    "https://www.theguardian.com/world/rss",
    "https://feeds.thelocal.com/rss/es",
    "https://www.upguard.com/breaches/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
]

redis_conn = Redis(host="localhost", port=6379, db=0)

queue = Queue(
    "article_processing",
    connection=redis_conn,
)

def collect():
    for feed_url in RSS_FEEDS:
        print(f"Parsing {feed_url}")

        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:20]:
            if redis_conn.sadd("seen_urls", entry.link):
                queue.enqueue(
                    process_article,
                    entry.link,
                    entry.title,
                    getattr(entry, "published", None),
                    job_timeout="10m",
                )

                print(f"Enqueued: {entry.title}")

if __name__ == "__main__":
    collect()