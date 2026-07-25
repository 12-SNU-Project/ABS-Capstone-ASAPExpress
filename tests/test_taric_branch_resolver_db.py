from bussiness_logic.classification.services import taric_branch_resolver


def test_resolver_groups_database_rows_by_taric10(monkeypatch) -> None:
    rows = (
        {
            "cn8": "19021990",
            "goods_code_10": "1902199010",
            "row_kind": "nomenclature_only",
            "line_id": "line-1",
            "productline_suffix": "10",
            "leaf_description_en": "Other",
            "is_declarable_leaf": True,
        },
        {
            "cn8": "19021990",
            "goods_code_10": "1902199010",
            "row_kind": "measure_line",
            "measure_type_description": "Third country duty",
            "applies_to_korea": True,
        },
    )
    monkeypatch.setattr(
        taric_branch_resolver,
        "_load_rows_from_db",
        lambda _cn8: rows,
    )

    branches = taric_branch_resolver.TaricBranchResolverTool().resolve(
        "19021990"
    )

    assert len(branches) == 1
    assert branches[0].taric10 == "1902199010"
    assert branches[0].measure_type_summary == ["Third country duty"]
    assert branches[0].is_declarable_leaf is True


def test_resolver_batches_final_candidates(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    rows = (
        {
            "cn8": "19021990",
            "goods_code_10": "1902199010",
            "row_kind": "nomenclature_only",
            "is_declarable_leaf": True,
        },
        {
            "cn8": "16042005",
            "goods_code_10": "1604200500",
            "row_kind": "nomenclature_only",
            "is_declarable_leaf": True,
        },
    )

    def load(candidateCodes: tuple[str, ...]):
        calls.append(candidateCodes)
        return rows

    monkeypatch.setattr(taric_branch_resolver, "_load_rows_for_cn8s", load)

    resolved = taric_branch_resolver.TaricBranchResolverTool().resolve_many(
        ["19021990", "16042005"]
    )

    assert calls == [("19021990", "16042005")]
    assert resolved["19021990"][0].taric10 == "1902199010"
    assert resolved["16042005"][0].taric10 == "1604200500"
