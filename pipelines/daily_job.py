"""Entry point for a scheduled run (Databricks job, cron or GitHub Actions)."""

import sys

from freshlens.cli import main

if __name__ == "__main__":
    sys.exit(main(["daily", *sys.argv[1:]]))
