#!/usr/bin/env python
"""Standalone DB initialization/inspection utility.

Useful for CI, packaging smoke tests, or a support engineer diagnosing a
user's install without launching the full GUI:

    python scripts/init_db.py            # creates/migrates the DB, prints its path
    python scripts/init_db.py --stats    # also prints job counts by status
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from instacore_sync.core.config import AppSettings  # noqa: E402
from instacore_sync.db.database import Database  # noqa: E402
from instacore_sync.db.repositories.jobs_repository import JobsRepository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", action="store_true", help="Print job counts by status")
    args = parser.parse_args()

    settings = AppSettings.load()
    database = Database(settings.db_path)
    database.ensure_migrated()
    print(f"Database ready at: {settings.db_path}")

    if args.stats:
        jobs_repo = JobsRepository(database)
        counts = jobs_repo.counts_by_status()
        if not counts:
            print("No jobs recorded yet.")
        for status, count in counts.items():
            print(f"  {status.value:<16} {count}")


if __name__ == "__main__":
    main()
