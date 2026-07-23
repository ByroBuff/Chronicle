import os
import time

from collector.collector import collect


def main() -> None:
    interval = max(
        60,
        int(os.getenv("COLLECT_INTERVAL_SECONDS", "900")),
    )

    run_once = os.getenv(
        "COLLECT_ONCE",
        "false",
    ).lower() in {
        "1",
        "true",
        "yes",
    }

    while True:
        try:
            collect()
        except Exception as exc:
            print(
                f"Collection pass failed: {exc}",
                flush=True,
            )

        if run_once:
            return

        print(
            f"Next collection pass in {interval} seconds",
            flush=True,
        )

        time.sleep(interval)


if __name__ == "__main__":
    main()