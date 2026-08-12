"""PostgreSQL client for pre-classification chapter index rows."""

from __future__ import annotations

from collections.abc import Mapping
import logging

from db.db_session_manager import DbSessionManager

LOGGER = logging.getLogger(__name__)

_CHAPTER_INDEX_TABLE = "cn_chapter_index"
_COLUMN_QUERY = """
SELECT column_name
FROM information_schema.columns
WHERE table_name = :table_name
ORDER BY ordinal_position
"""


def _NormalizeChapterRow(row: Mapping[str, object]) -> Mapping[str, object]:
    normalized = dict(row)
    if not normalized.get("chapter") and normalized.get("chapter_id") is not None:
        normalized["chapter"] = normalized.get("chapter_id")
    return normalized


def _OrderColumn(columnNames: set[str]) -> str:
    if "chapter" in columnNames:
        return "chapter"
    if "chapter_id" in columnNames:
        return "chapter_id"
    return ""


def LoadPreClassificationChapterRowsFromDb() -> tuple[Mapping[str, object], ...]:
    """Load ``cn_chapter_index`` rows through the shared DB helper.

    The DB connection lifecycle is intentionally isolated here so upstream callers
    do not depend on low-level connection internals.
    """
    try:
        manager = DbSessionManager.GetInstance()
        if not manager.TableExists(_CHAPTER_INDEX_TABLE):
            return ()
        columnRows = manager.FetchRows(_COLUMN_QUERY, {"table_name": _CHAPTER_INDEX_TABLE})
        columnNames = {str(row.get("column_name") or "") for row in columnRows}
        orderColumn = _OrderColumn(columnNames)
        orderClause = f' ORDER BY "{orderColumn}"' if orderColumn else ""
        rows = manager.FetchRows(f"SELECT * FROM {_CHAPTER_INDEX_TABLE}{orderClause}")
        return tuple(_NormalizeChapterRow(row) for row in rows)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "Failed to load cn_chapter_index from PostgreSQL: %s", exc
        )
        return ()
