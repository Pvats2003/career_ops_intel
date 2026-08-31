"""Streaming SHA-256 hashing, sized so a 150 MB video never blows up memory."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB


class HashService:
    """Computes the SHA-256 of a file without loading it fully into memory."""

    def sha256_of_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            while chunk := fh.read(_CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest()
