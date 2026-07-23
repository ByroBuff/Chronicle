# queue.py

from redis import Redis
from rq import Queue

redis_conn = Redis(
    host="localhost",
    port=6379,
    db=0
)

article_queue = Queue(
    "article_processing",
    connection=redis_conn
)