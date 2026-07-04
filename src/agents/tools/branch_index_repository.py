"""Branch-index read adapter for staged narrowing (P2).

Reads the Supabase tables loaded by ``load_branch_indexes.py`` —
``hs4_branch_index`` / ``hs6_branch_index`` / ``cn8_branch_index`` — which hold,
for every CN branching point, the node-local decision criterion
(positive/negative terms, quantitative conditions, residual flag, and which
ProductUnderstanding DTO fields answer it). Verified 1:1 against cn_table.

Follows the chapter_index_repository convention: DbSessionManager boundary,
degrade to () on any failure so staged falls back to the cn_table path.
"""
from __future__ import annotations

from typing import Mapping

_STAGE_TABLES = {
    "hs4": "hs4_branch_index",
    "hs6": "hs6_branch_index",
    "cn8": "cn8_branch_index",
}


def LoadBranchRows(stage: str, parentCodes: tuple[str, ...]) -> tuple[Mapping[str, object], ...]:
    """Branch rows (children + their decision criteria) under the given parents."""
    table = _STAGE_TABLES.get(stage)
    if not table or not parentCodes:
        return ()
    try:
        from sqlalchemy import bindparam, text

        from db.db_session_manager import DbSessionManager
    except Exception:  # noqa: BLE001
        return ()
    try:
        manager = DbSessionManager.GetInstance()
        rows = manager.FetchRows(
            text(
                f'SELECT * FROM "{table}" WHERE parent_code IN :parents ORDER BY code',
            ).bindparams(bindparam("parents", expanding=True)),
            {"parents": tuple(parentCodes)},
        )
        return tuple(dict(row) for row in rows)
    except Exception:  # noqa: BLE001
        return ()
