from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_instacore_sync.db"


@pytest.fixture
def database(tmp_db_path: Path):
    from instacore_sync.db.database import Database

    db = Database(tmp_db_path)
    db.ensure_migrated()
    yield db
    db.close()
