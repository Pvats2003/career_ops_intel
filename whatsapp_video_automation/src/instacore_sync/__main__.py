"""CLI entry point — `python -m instacore_sync` or the `instacore-sync` console script."""

from __future__ import annotations

import sys


def main() -> None:
    from instacore_sync.app import run

    sys.exit(run())


if __name__ == "__main__":
    main()
