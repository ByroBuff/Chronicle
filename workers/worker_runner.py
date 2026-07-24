import os

from redis import Redis
from rq import Queue, Worker

# Import these before RQ forks the job process.
# This loads spaCy and the model once in the parent worker.
import workers.entity_extractor
import workers.worker


def main() -> None:
    connection = Redis(
        host=os.environ["REDIS_HOST"],
        port=int(os.environ["REDIS_PORT"]),
        db=int(os.environ["REDIS_DB"]),
    )

    queue_name = os.environ.get(
        "RQ_QUEUE",
        "article_processing",
    )

    queue = Queue(
        queue_name,
        connection=connection,
    )

    worker = Worker(
        [queue],
        connection=connection,
    )

    worker.work()


if __name__ == "__main__":
    main()