"""Database-backed runtime assets shared by product and classification stages.

Runtime authority must not depend on ignored workstation files. Each migrated
asset has a dedicated PostgreSQL table and is loaded through this repository.
Missing required tables or rows fail explicitly so a clean checkout cannot
silently run with reduced classification behavior.
"""

from __future__ import annotations

from functools import lru_cache
import json
from typing import Any

from db.db_session_manager import DbSessionManager


class RuntimeAssetUnavailableError(RuntimeError):
    """Raised when a required database-backed runtime asset is unavailable."""


def _Manager() -> DbSessionManager:
    return DbSessionManager.GetInstance()


def _RequireTable(tableName: str) -> None:
    if not _Manager().TableExists(tableName):
        raise RuntimeAssetUnavailableError(
            f"Required runtime asset table is missing: {tableName}"
        )


def _DecodeJson(value: object, *, tableName: str) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        raise RuntimeAssetUnavailableError(
            f"Runtime asset table has no payload: {tableName}"
        )
    try:
        return json.loads(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeAssetUnavailableError(
            f"Runtime asset payload is invalid JSON: {tableName}"
        ) from exc


@lru_cache(maxsize=None)
def _TableColumns(tableName: str) -> frozenset[str]:
    if not _Manager().TableExists(tableName):
        return frozenset()
    rows = _Manager().FetchRows(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = :table_name
        """,
        {"table_name": tableName},
    )
    return frozenset(
        str(row.get("column_name") or "")
        for row in rows
        if str(row.get("column_name") or "")
    )


@lru_cache(maxsize=None)
def LoadSingletonAsset(tableName: str) -> dict[str, Any]:
    """Load the active JSON payload from a one-row versioned asset table."""
    _RequireTable(tableName)
    rows = _Manager().FetchRows(
        f"""
        SELECT payload
        FROM {tableName}
        WHERE is_active = TRUE
        ORDER BY updated_at DESC
        LIMIT 1
        """
    )
    if not rows:
        raise RuntimeAssetUnavailableError(
            f"Runtime asset table has no active row: {tableName}"
        )
    payload = _DecodeJson(rows[0].get("payload"), tableName=tableName)
    if not isinstance(payload, dict):
        raise RuntimeAssetUnavailableError(
            f"Runtime asset payload must be an object: {tableName}"
        )
    return payload


@lru_cache(maxsize=None)
def LoadStandardNameDictionary() -> tuple[dict[str, Any], ...]:
    tableName = "std_name_dictionary"
    _RequireTable(tableName)
    rows = _Manager().FetchRows(
        """
        SELECT ko, en, hs6, hs10, spec_ko, spec_en
        FROM std_name_dictionary
        ORDER BY dictionary_id
        """
    )
    if not rows:
        raise RuntimeAssetUnavailableError(
            "Runtime asset table has no rows: std_name_dictionary"
        )
    return tuple(dict(row) for row in rows)


@lru_cache(maxsize=None)
def LoadCuratedTermBridge() -> tuple[dict[str, Any], ...]:
    tableName = "curated_term_bridge"
    _RequireTable(tableName)
    rows = _Manager().FetchRows(
        """
        SELECT ko, en, source, derivation, approved_by, approved_date, hs6
        FROM curated_term_bridge
        ORDER BY bridge_id
        """
    )
    return tuple(
        {
            **dict(row),
            "date": row.get("approved_date"),
        }
        for row in rows
    )


def EnqueueTermReview(normalizedTerm: str, rawTerm: str) -> None:
    """Persist one unmatched term without creating workstation artifacts."""
    tableName = "std_name_review_queue"
    _RequireTable(tableName)
    with _Manager().OpenRawConnection() as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO std_name_review_queue
                        (normalized_term, raw_term, first_seen_at, last_seen_at)
                    VALUES (%s, %s, now(), now())
                    ON CONFLICT (normalized_term) DO UPDATE SET
                        raw_term = EXCLUDED.raw_term,
                        last_seen_at = now(),
                        seen_count = std_name_review_queue.seen_count + 1
                    """,
                    (normalizedTerm, rawTerm),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


@lru_cache(maxsize=None)
def LoadFoodTypeDictionary() -> dict[str, str]:
    tableName = "food_type_dictionary"
    _RequireTable(tableName)
    rows = _Manager().FetchRows(
        """
        SELECT ko_term, en_term
        FROM food_type_dictionary
        ORDER BY ko_term
        """
    )
    if not rows:
        raise RuntimeAssetUnavailableError(
            "Runtime asset table has no rows: food_type_dictionary"
        )
    return {
        str(row.get("ko_term") or ""): str(row.get("en_term") or "")
        for row in rows
        if str(row.get("ko_term") or "")
    }


@lru_cache(maxsize=None)
def LoadClassificationCriterionTaxonomy() -> tuple[dict[str, Any], ...]:
    tableName = "classification_criterion_taxonomy"
    _RequireTable(tableName)
    rows = _Manager().FetchRows(
        """
        SELECT payload
        FROM classification_criterion_taxonomy
        ORDER BY criterion_id
        """
    )
    return tuple(
        _DecodeJson(row.get("payload"), tableName=tableName)
        for row in rows
    )


@lru_cache(maxsize=None)
def LoadProductInputDictionary() -> tuple[dict[str, Any], ...]:
    tableName = "product_input_dictionary"
    if not _Manager().TableExists(tableName):
        return ()
    rows = _Manager().FetchRows(
        """
        SELECT
            term_id,
            canonical_name,
            term_type,
            aliases,
            source_name,
            source_id,
            source_url,
            updated_at
        FROM product_input_dictionary
        ORDER BY term_id
        """
    )
    return tuple(dict(row) for row in rows)


def _NormalizeClassificationCodes(codes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            normalized
            for code in codes
            if len(
                normalized := "".join(
                    character
                    for character in str(code)
                    if character.isdigit()
                )[:8]
            ) >= 4
        )
    )


@lru_cache(maxsize=128)
def _LoadBtiCasePool(normalizedCodes: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    """Fetch one union pool for all final candidates in a classification run."""
    if not normalizedCodes:
        return ()
    cn8Codes = list(normalizedCodes)
    hs6Codes = list(dict.fromkeys(code[:6] for code in normalizedCodes))
    hs4Codes = list(dict.fromkeys(code[:4] for code in normalizedCodes))
    rowsByReference: dict[str, dict[str, Any]] = {}
    for tableName in ("bti_case_evidence", "bti_case", "bti_case_full"):
        columns = _TableColumns(tableName)
        if "cn8" not in columns:
            continue
        conditions = [
            "cn8 = ANY(:cn8_codes)",
            "left(cn8, 4) = ANY(:hs4_codes)",
        ]
        if "hs6" in columns:
            conditions.insert(1, "hs6 = ANY(:hs6_codes)")
        rows = _Manager().FetchRows(
            f"""
            SELECT *
            FROM {tableName}
            WHERE {" OR ".join(conditions)}
            LIMIT :row_limit
            """,
            {
                "cn8_codes": cn8Codes,
                "hs6_codes": hs6Codes,
                "hs4_codes": hs4Codes,
                "row_limit": 1000 * len(normalizedCodes),
            },
        )
        for ordinal, row in enumerate(rows):
            payload = dict(row)
            payload["_source_table"] = tableName
            reference = str(
                payload.get("bti_reference")
                or payload.get("reference")
                or f"{tableName}:{ordinal}:{payload.get('cn8') or ''}"
            )
            rowsByReference.setdefault(reference, payload)
    return tuple(rowsByReference.values())


def LoadBtiCasesForCodes(
    codes: tuple[str, ...] | list[str],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Return per-code EBTI pools after one batched database fetch."""
    normalizedCodes = _NormalizeClassificationCodes(tuple(codes))
    pool = _LoadBtiCasePool(normalizedCodes)
    byCode: dict[str, tuple[dict[str, Any], ...]] = {}
    for code in normalizedCodes:
        hs6 = code[:6]
        hs4 = code[:4]
        byCode[code] = tuple(
            row
            for row in pool
            if (
                normalizedRowCode := "".join(
                    character
                    for character in str(row.get("cn8") or "")
                    if character.isdigit()
                )[:8]
            )
            and (
                normalizedRowCode == code
                or normalizedRowCode.startswith(hs6)
                or normalizedRowCode.startswith(hs4)
            )
        )
    return byCode


@lru_cache(maxsize=512)
def LoadBtiCasesForCode(code: str) -> tuple[dict[str, Any], ...]:
    """Compatibility wrapper for callers that request one code."""
    normalizedCodes = _NormalizeClassificationCodes((code,))
    if not normalizedCodes:
        return ()
    normalizedCode = normalizedCodes[0]
    return LoadBtiCasesForCodes(normalizedCodes).get(normalizedCode, ())


@lru_cache(maxsize=None)
def LoadCoiProductMap() -> dict[str, tuple[str, ...]]:
    tableName = "coi_product_map"
    _RequireTable(tableName)
    rows = _Manager().FetchRows(
        """
        SELECT product_name, form_key
        FROM coi_product_map
        ORDER BY product_name, form_key
        """
    )
    grouped: dict[str, list[str]] = {}
    for row in rows:
        productName = str(row.get("product_name") or "")
        formKey = str(row.get("form_key") or "")
        if productName and formKey:
            grouped.setdefault(productName, []).append(formKey)
    return {key: tuple(values) for key, values in grouped.items()}


@lru_cache(maxsize=None)
def LoadCoiForms() -> dict[str, dict[str, Any]]:
    tableName = "coi_form"
    _RequireTable(tableName)
    rows = _Manager().FetchRows(
        """
        SELECT form_key, payload
        FROM coi_form
        WHERE is_active = TRUE
        ORDER BY form_key
        """
    )
    return {
        str(row.get("form_key") or ""): _DecodeJson(
            row.get("payload"),
            tableName=tableName,
        )
        for row in rows
        if str(row.get("form_key") or "")
    }


@lru_cache(maxsize=None)
def LoadCoProductMap() -> dict[str, tuple[str, ...]]:
    tableName = "co_product_map"
    if not _Manager().TableExists(tableName):
        return {}
    rows = _Manager().FetchRows(
        """
        SELECT product_name, form_key
        FROM co_product_map
        ORDER BY product_name, form_key
        """
    )
    grouped: dict[str, list[str]] = {}
    for row in rows:
        productName = str(row.get("product_name") or "")
        formKey = str(row.get("form_key") or "")
        if productName and formKey:
            grouped.setdefault(productName, []).append(formKey)
    return {key: tuple(values) for key, values in grouped.items()}


@lru_cache(maxsize=None)
def LoadCoForms() -> dict[str, dict[str, Any]]:
    tableName = "co_form"
    if not _Manager().TableExists(tableName):
        return {}
    rows = _Manager().FetchRows(
        """
        SELECT form_key, payload
        FROM co_form
        WHERE is_active = TRUE
        ORDER BY form_key
        """
    )
    return {
        str(row.get("form_key") or ""): _DecodeJson(
            row.get("payload"),
            tableName=tableName,
        )
        for row in rows
        if str(row.get("form_key") or "")
    }


def ClearRuntimeAssetCaches() -> None:
    """Clear process caches after tests or an explicit runtime asset refresh."""
    LoadSingletonAsset.cache_clear()
    LoadStandardNameDictionary.cache_clear()
    LoadCuratedTermBridge.cache_clear()
    LoadFoodTypeDictionary.cache_clear()
    LoadClassificationCriterionTaxonomy.cache_clear()
    LoadProductInputDictionary.cache_clear()
    LoadBtiCasesForCode.cache_clear()
    _LoadBtiCasePool.cache_clear()
    LoadCoiProductMap.cache_clear()
    LoadCoiForms.cache_clear()
    LoadCoProductMap.cache_clear()
    LoadCoForms.cache_clear()
    _TableColumns.cache_clear()
