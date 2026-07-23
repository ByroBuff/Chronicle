import os

from redis import Redis
from rq import Queue


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
QUEUE_NAME = os.getenv("RQ_QUEUE", "article_processing")


redis_conn = Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=False,
)

article_queue = Queue(
    QUEUE_NAME,
    connection=redis_conn,
)