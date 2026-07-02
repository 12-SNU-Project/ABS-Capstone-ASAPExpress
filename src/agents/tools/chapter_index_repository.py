"""Chapter index read adapter for pre-classification routing."""

from __future__ import annotations

from typing import Mapping
from .chapter_index_client import LoadPreClassificationChapterRowsFromDb


def LoadPreClassificationChapterRows() -> tuple[Mapping[str, object], ...]:
    """Load chapter index rows for deterministic pre-classification routing."""

    return LoadPreClassificationChapterRowsFromDb()
