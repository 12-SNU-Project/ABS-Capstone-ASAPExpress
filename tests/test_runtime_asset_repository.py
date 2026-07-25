from __future__ import annotations

import pytest

from bussiness_logic.core import runtime_asset_repository as repository


class _FakeManager:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = tables
        self.fetches: list[str] = []

    def TableExists(self, tableName: str) -> bool:
        return tableName in self.tables

    def FetchRows(self, sql: str, parameters: dict | None = None):
        text = str(sql)
        self.fetches.append(text)
        parameters = parameters or {}
        if "information_schema.columns" in text:
            tableName = str(parameters.get("table_name") or "")
            columns = {
                key
                for row in self.tables.get(tableName, [])
                for key in row
            }
            return tuple({"column_name": column} for column in sorted(columns))
        for tableName, rows in self.tables.items():
            if f"FROM {tableName}" in text:
                return tuple(rows)
        return ()


@pytest.fixture(autouse=True)
def _clear_caches():
    repository.ClearRuntimeAssetCaches()
    yield
    repository.ClearRuntimeAssetCaches()


def test_required_singleton_missing_fails_explicitly(monkeypatch) -> None:
    monkeypatch.setattr(repository, "_Manager", lambda: _FakeManager({}))

    with pytest.raises(
        repository.RuntimeAssetUnavailableError,
        match="heading_axis_map",
    ):
        repository.LoadSingletonAsset("heading_axis_map")


def test_singleton_payload_is_loaded(monkeypatch) -> None:
    manager = _FakeManager(
        {
            "heading_axis_map": [
                {
                    "payload": {"headings": {"1902": "product_identity"}},
                    "is_active": True,
                }
            ]
        }
    )
    monkeypatch.setattr(repository, "_Manager", lambda: manager)

    payload = repository.LoadSingletonAsset("heading_axis_map")

    assert payload["headings"]["1902"] == "product_identity"


def test_bti_pool_is_loaded_only_from_database_tables(monkeypatch) -> None:
    manager = _FakeManager(
        {
            "bti_case_evidence": [
                {
                    "bti_reference": "DE-1",
                    "cn8": "19021990",
                    "hs6": "190219",
                    "keywords": "uncooked pasta not stuffed",
                }
            ]
        }
    )
    monkeypatch.setattr(repository, "_Manager", lambda: manager)

    rows = repository.LoadBtiCasesForCode("19021990")

    assert len(rows) == 1
    assert rows[0]["bti_reference"] == "DE-1"
    assert rows[0]["_source_table"] == "bti_case_evidence"


def test_bti_candidate_set_uses_one_data_query(monkeypatch) -> None:
    manager = _FakeManager(
        {
            "bti_case_evidence": [
                {
                    "bti_reference": "DE-1",
                    "cn8": "19021990",
                    "hs6": "190219",
                    "keywords": "uncooked pasta not stuffed",
                },
                {
                    "bti_reference": "DE-2",
                    "cn8": "16042005",
                    "hs6": "160420",
                    "keywords": "prepared fish product",
                },
            ]
        }
    )
    monkeypatch.setattr(repository, "_Manager", lambda: manager)

    byCode = repository.LoadBtiCasesForCodes(["19021990", "16042005"])

    assert len(byCode["19021990"]) == 1
    assert len(byCode["16042005"]) == 1
    dataQueries = [
        query
        for query in manager.fetches
        if "FROM bti_case_evidence" in query
    ]
    assert len(dataQueries) == 1
