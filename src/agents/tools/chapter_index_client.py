"""PostgreSQL client for pre-classification chapter index rows."""

from __future__ import annotations

from collections.abc import Mapping
import logging

from db.db_session_manager import DbSessionManager

LOGGER = logging.getLogger(__name__)


def LoadPreClassificationChapterRowsFromDb() -> tuple[Mapping[str, object], ...]:
    """Load ``cn_chapter_index`` rows through the shared DB helper.

    The DB connection lifecycle is intentionally isolated here so upstream callers
    do not depend on low-level connection internals.
    """
    try:
        manager = DbSessionManager.GetInstance()
        if not manager.TableExists("cn_chapter_index"):
            return ()
        return manager.FetchRows("SELECT * FROM cn_chapter_index ORDER BY chapter")
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "Failed to load cn_chapter_index from PostgreSQL: %s", exc
        )
        return ()
