from database import setup_database
from collector.collector import collect

setup_database()
collect()