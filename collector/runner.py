import os
import time

from collector.collector import collect


def main() -> None:
    tick_seconds = max(30, int(os.getenv("COLLECTOR_TICK_SECONDS", "60")))

    print(
        f"Collector scheduler running every {tick_seconds} seconds",
        flush=True,
    )

    while True:
        try:
            collect()
        except Exception as exc:
            print(
                f"Collection pass failed: {exc}",
                flush=True,
            )

        time.sleep(tick_seconds)


if __name__ == "__main__":
    main()