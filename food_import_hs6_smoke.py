"""Synthetic food-import HS6 smoke using the same classification input path."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT_PATH = Path(__file__).resolve().parent
SOURCE_ROOT_PATH = PROJECT_ROOT_PATH / "src"
if str(SOURCE_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT_PATH))


DEFAULT_CSV_PATH = PROJECT_ROOT_PATH / "data" / "food_import_testset_final.csv"
DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT_PATH / "artifacts" / "food_import_hs6_smoke"
DEFAULT_EXPECTED_COLUMN = "existing_hs6"


def ParseArguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate HS6 classification against food_import_testset_final.csv "
            "through EvidenceIntakeAgent -> ClassificationAgent."
        ),
    )
    parser.add_argument("--csv-path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--expected-column",
        default=DEFAULT_EXPECTED_COLUMN,
        help="HS6 정답으로 볼 컬럼입니다. 기본 existing_hs6.",
    )
    parser.add_argument("--summary-path", type=Path, default=None)
    parser.add_argument("--print-mismatches", action="store_true")
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be greater than 0")
    if args.offset < 0:
        parser.error("--offset must be greater than or equal to 0")
    return args


def IterRows(csvPath: Path, *, offset: int, limit: int) -> Iterator[dict[str, str]]:
    with csvPath.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for rowIndex, row in enumerate(reader):
            if rowIndex < offset:
                continue
            if rowIndex >= offset + limit:
                break
            yield {str(key): str(value or "") for key, value in row.items()}


def NormalizeHs6(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:6]


def BuildDatasetFacts(row: Mapping[str, str]) -> dict[str, Any]:
    productName = row.get("korean_name") or row.get("english_name_original") or ""
    factTexts = [
        text
        for text in [
            row.get("product_input_for_rag", ""),
            row.get("main_ingredients_original", ""),
            row.get("kurly_short_description", ""),
            row.get("kurly_keyword", ""),
            row.get("english_name_original", ""),
        ]
        if text.strip()
    ]
    productFacts = [
        {
            "field_name": fieldName,
            "raw_value": value,
            "normalized_value": value,
            "source_refs": ["food_import_testset_final.csv"],
            "correction_type": "synthetic_dataset",
        }
        for fieldName, value in [
            ("product_name", productName),
            ("product_input_for_rag", row.get("product_input_for_rag", "")),
            ("main_ingredients", row.get("main_ingredients_original", "")),
        ]
        if value.strip()
    ]
    inputReconstruction = {
        "mode": "synthetic_dataset",
        "used_llm_reconstruction": True,
        "classification_input_product_facts": productFacts,
        "classification_input_fact_texts": factTexts,
        "unresolved_product_facts": [],
        "product_fact_conflicts": [],
    }
    return {
        "url": row.get("kurly_url") or "",
        "source_urls": [row["kurly_url"]] if row.get("kurly_url") else [],
        "product_id": row.get("master_code") or row.get("NO") or "",
        "product_name": productName,
        "description": row.get("english_name_original") or row.get("product_input_for_rag") or "",
        "product_domain": "food",
        "classification_input_product_facts": productFacts,
        "classification_input_fact_texts": factTexts,
        "unresolved_product_facts": [],
        "product_fact_conflicts": [],
        "ocr_text": factTexts,
        "origin_country": "KR",
        "intended_use": "human consumption",
        "input_reconstruction": inputReconstruction,
    }


def RunFullClassification(
    row: Mapping[str, str],
    *,
    runRoot: Path,
) -> dict[str, Any]:
    from agents.blackboard import BlackboardStore
    from agents.classification_agent import ClassificationAgent
    from agents.document_pipeline import build_raw_input_from_ui
    from agents.evidence_intake_agent import EvidenceIntakeAgent

    facts = BuildDatasetFacts(row)
    rawInput = build_raw_input_from_ui(
        query=str(facts.get("product_name") or row.get("NO") or ""),
        facts=facts,
    )
    runId = "run_{0:06d}".format(int(row.get("NO") or 0))
    store = BlackboardStore.create(
        runtime_mode="food_import_hs6_smoke",
        run_id=runId,
        run_dir=runRoot / str(row.get("NO") or runId),
        validate_on_write=False,
    )
    agentResults = []
    for agent in (EvidenceIntakeAgent(rawInput), ClassificationAgent()):
        result = agent.execute(store)
        agentResults.append({
            "agent_name": agent.agent_name,
            "success": result.success,
            "error": result.error,
            "outputs_written": result.outputs_written,
        })
        if not result.success:
            break
    candidateSet = (store.load().get("candidate_code_sets") or [None])[-1]
    if not isinstance(candidateSet, dict):
        candidateSet = {}
    return {
        "mode": "llm_classification_with_backtracking",
        "candidates": BuildCandidateRows(candidateSet.get("candidates") or []),
        "decision": candidateSet.get("classification_trace") or {},
        "agent_results": agentResults,
        "run_dir": str(store.run_dir),
    }


def BuildCandidateRows(candidates: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            continue
        staticTree = candidate.get("candidate_static_tree") or {}
        if not isinstance(staticTree, dict):
            staticTree = {}
        rows.append({
            "rank": candidate.get("rank") or index,
            "cn8": candidate.get("cn8") or str(candidate.get("hs8") or "")[:8],
            "hs6": candidate.get("hs6") or str(candidate.get("cn8") or candidate.get("hs8") or "")[:6],
            "score": staticTree.get("total_score"),
            "llm_recommended": bool(candidate.get("llm_recommended")),
            "matched_keywords": staticTree.get("matched_keywords") or [],
        })
    return rows


def BuildEvaluationRow(
    sourceRow: Mapping[str, str],
    classification: Mapping[str, Any],
    *,
    expectedColumn: str,
) -> dict[str, Any]:
    expectedHs6 = NormalizeHs6(sourceRow.get(expectedColumn))
    candidates = list(classification.get("candidates") or [])
    selectedCandidate = next(
        (candidate for candidate in candidates if candidate.get("llm_recommended")),
        candidates[0] if candidates else {},
    )
    predictedHs6 = str(selectedCandidate.get("hs6") or "") if selectedCandidate else ""
    candidateHs6 = [str(candidate.get("hs6") or "") for candidate in candidates]
    return {
        "row_no": sourceRow.get("NO"),
        "master_code": sourceRow.get("master_code"),
        "product_name": sourceRow.get("korean_name") or sourceRow.get("english_name_original"),
        "expected_column": expectedColumn,
        "expected_hs6": expectedHs6,
        "predicted_hs6": predictedHs6,
        "prediction_source": "llm_recommended" if selectedCandidate.get("llm_recommended") else "rank1_fallback",
        "top1_match": bool(expectedHs6 and predictedHs6 == expectedHs6),
        "top5_match": bool(expectedHs6 and expectedHs6 in candidateHs6[:5]),
        "existing_hs6": NormalizeHs6(sourceRow.get("existing_hs6")),
        "asap_x_hs6": NormalizeHs6(sourceRow.get("asap_x_hs6")),
        "candidates": candidates,
        "decision": classification.get("decision") or {},
        "agent_results": classification.get("agent_results") or [],
        "run_dir": classification.get("run_dir"),
    }


def BuildSummary(results: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    total = len(results)
    top1 = sum(1 for result in results if result["top1_match"])
    top5 = sum(1 for result in results if result["top5_match"])
    return {
        "mode": mode,
        "total": total,
        "top1_match_count": top1,
        "top5_match_count": top5,
        "top1_accuracy": round(top1 / total, 4) if total else 0.0,
        "top5_recall": round(top5 / total, 4) if total else 0.0,
    }


def Main() -> None:
    args = ParseArguments()
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    runRoot = DEFAULT_ARTIFACT_ROOT / timestamp
    summaryPath = args.summary_path or (runRoot / "summary.json")
    results: list[dict[str, Any]] = []
    for sourceRow in IterRows(args.csv_path, offset=args.offset, limit=args.limit):
        classification = RunFullClassification(sourceRow, runRoot=runRoot / "runs")
        evaluation = BuildEvaluationRow(
            sourceRow,
            classification,
            expectedColumn=args.expected_column,
        )
        results.append(evaluation)
        if args.print_mismatches and not evaluation["top1_match"]:
            print(
                "mismatch row={0} expected={1} predicted={2} name={3}".format(
                    evaluation["row_no"],
                    evaluation["expected_hs6"],
                    evaluation["predicted_hs6"],
                    evaluation["product_name"],
                ),
            )

    output = {
        "dataset": str(args.csv_path),
        "expected_column": args.expected_column,
        "offset": args.offset,
        "limit": args.limit,
        "summary": BuildSummary(results, mode="llm_classification_with_backtracking"),
        "results": results,
    }
    summaryPath.parent.mkdir(parents=True, exist_ok=True)
    summaryPath.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print("summary_path={0}".format(summaryPath))


if __name__ == "__main__":
    Main()
