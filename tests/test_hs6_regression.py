import json
from pathlib import Path
from typing import Any

from bussiness_logic.core.classification.stage1 import (
    CnCandidateRetriever,
    ProductClassificationInput,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests/fixtures/hs6_regression_cases.json"


def _LoadCases() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _BuildProductInput(case: dict[str, Any]) -> ProductClassificationInput:
    return ProductClassificationInput(
        productName=str(case["product_name"]),
        shortDescription=str(case["short_description"]),
        productDomain="food_16_21",
        domainScopes=["food_16_21"],
        normalizedOcrFactTexts=[
            str(value) for value in case["normalized_fact_texts"]
        ],
    )


def _ReadUniqueHs6Codes(candidates: list[Any]) -> list[str]:
    hs6Codes: list[str] = []
    for candidate in candidates:
        hs6Code = candidate.hs6Code
        if hs6Code and hs6Code not in hs6Codes:
            hs6Codes.append(hs6Code)
    return hs6Codes


def test_hs6_regression_fixture_sources_and_labels_are_available() -> None:
    retriever = CnCandidateRetriever(
        PROJECT_ROOT / "docs/ASAP_Ontology_v1",
        PROJECT_ROOT,
    )
    knownHs6Codes = {
        row.get("subheading", "")
        for rows in retriever.LoadRowsByDomainScope().values()
        for row in rows
    }

    for case in _LoadCases():
        assert (PROJECT_ROOT / case["source_artifact"]).is_file()
        assert case["expected_hs6"] in knownHs6Codes
        assert case["label_basis"] == "US HS6 proxy from data/answer.csv"


def test_hs6_static_beam_regression_recall() -> None:
    retriever = CnCandidateRetriever(
        PROJECT_ROOT / "docs/ASAP_Ontology_v1",
        PROJECT_ROOT,
    )
    rankedResults: list[tuple[str, str, list[str], int | None]] = []
    for case in _LoadCases():
        candidates = retriever.FindCandidates(
            _BuildProductInput(case),
            topK=5,
        )
        hs6Codes = _ReadUniqueHs6Codes(candidates)
        expectedHs6 = str(case["expected_hs6"])
        rank = (
            hs6Codes.index(expectedHs6) + 1
            if expectedHs6 in hs6Codes
            else None
        )
        rankedResults.append(
            (str(case["case_id"]), expectedHs6, hs6Codes, rank)
        )

    caseCount = len(rankedResults)
    recallAt1 = sum(rank == 1 for *_, rank in rankedResults) / caseCount
    recallAt3 = sum(
        rank is not None and rank <= 3 for *_, rank in rankedResults
    ) / caseCount
    recallAt5 = sum(
        rank is not None and rank <= 5 for *_, rank in rankedResults
    ) / caseCount

    print(
        json.dumps(
            {
                "case_count": caseCount,
                "recall_at_1": recallAt1,
                "recall_at_3": recallAt3,
                "recall_at_5": recallAt5,
                "results": [
                    {
                        "case_id": caseId,
                        "expected_hs6": expectedHs6,
                        "candidate_hs6_codes": hs6Codes,
                        "rank": rank,
                    }
                    for caseId, expectedHs6, hs6Codes, rank in rankedResults
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    assert recallAt1 >= 1 / 3
    assert recallAt3 >= 2 / 3
    assert recallAt5 == 1.0
