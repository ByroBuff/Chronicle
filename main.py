from collector.collector import collect
from database import setup_database


def main() -> None:
    setup_database()
    collect()


if __name__ == "__main__":
    main()