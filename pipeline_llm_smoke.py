"""URL-driven pipeline smoke for the restored LLM ProductUnderstanding combiner.

Reuses the classification-smoke wiring from ``kurly_market_smoke.py`` (commit
668cf10) — ``build_raw_input_from_ui`` (which scrapes the Kurly URL) + the
current component chain (EvidenceIntake -> ProductUnderstanding -> DomainRouter ->
Classification). For every URL in ``tests/EU_HS_test.csv`` it runs the chain
twice (``ASAP_USE_LLM_UNDERSTANDING`` off vs on) against the *same* scraped raw
input, then scores hs4/hs6/cn8 recall vs the ``EU HS CODE`` answer — so you can
see whether the LLM combiner lifts routing/classification accuracy.

CSV columns: ``상품 상세`` = product URL, ``EU HS CODE`` = 10-digit answer code.
Data paths stay on Supabase; the LLM goes through the bridge (gemini via
EU_EXPORT_LLM_*). Run inside conda ``asap`` with runtime keys loaded, e.g.:

  python pipeline_llm_smoke.py --limit 3
  python pipeline_llm_smoke.py --limit 3 --summary-path artifacts/pipeline_llm_smoke/summary.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path

PROJECT_ROOT_PATH = Path(__file__).resolve().parent

from bussiness_logic.utils.json_types import JsonObject  # noqa: E402

DEFAULT_CSV_PATH = PROJECT_ROOT_PATH / "tests" / "EU_HS_test.csv"
DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT_PATH / "artifacts" / "pipeline_llm_smoke"
URL_COLUMN = "상품 상세"
ANSWER_COLUMN = "EU HS CODE"
RECALL_LEVELS = (("hs2", 2), ("hs4", 4), ("hs6", 6), ("cn8", 8))


def ParseArguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="URL-driven LLM combiner pipeline smoke")
    parser.add_argument("--csv-path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--limit", type=int, default=3, help="처리할 URL 수(기본 3, 0이면 전체).")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--summary-path", type=Path, default=None)
    args = parser.parse_args(arguments)
    if args.limit < 0 or args.offset < 0:
        parser.error("--limit/--offset must be >= 0")
    return args


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def LoadRows(csvPath: Path, *, offset: int, limit: int) -> list[dict[str, str]]:
    with open(csvPath, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            answer = _digits(row.get(ANSWER_COLUMN))
            # EU codes have even length (8/10); an odd length means the CSV
            # dropped a leading zero (0710805920 -> "710805920").
            if len(answer) % 2 == 1:
                answer = "0" + answer
            rows.append({"url": (row.get(URL_COLUMN) or "").strip(), "answer": answer})
    rows = [r for r in rows if r["url"].startswith("http") and r["answer"]]
    rows = rows[offset:]
    return rows[:limit] if limit else rows


def _run_chain(rawInput: JsonObject, *, productId: str, use_llm: bool,
               artifact_root: Path) -> JsonObject:
    from agents.blackboard import BlackboardStore
    from agents.pipeline_components import (
        ClassificationComponent,
        Hs2RoutingComponent,
        EvidenceIntakeComponent,
        ProductUnderstandingComponent,
    )

    saved = {
        "ASAP_USE_LLM_UNDERSTANDING": os.environ.get("ASAP_USE_LLM_UNDERSTANDING"),
    }
    os.environ["ASAP_USE_LLM_UNDERSTANDING"] = "1" if use_llm else "0"
    try:
        runDirectory = (
            artifact_root / productId / ("llm_on" if use_llm else "llm_off")
            / datetime.now().strftime("%Y%m%dT%H%M%S%f")
        )
        store = BlackboardStore.create(
            runtime_mode="smoke", run_id="run_001",
            run_dir=runDirectory, validate_on_write=False,
        )
        errors: list[str] = []
        for component in (
            EvidenceIntakeComponent(rawInput),
            ProductUnderstandingComponent(),
            Hs2RoutingComponent(),
            ClassificationComponent(),
        ):
            result = component.Execute(store)
            if not result.success:
                errors.append(f"{component.component_name}: {result.error}")
                break

        bb = store.load()
        identity = (bb.get("product_understanding") or {}).get("identity_lane") or {}
        routing = bb.get("routing_context") or {}
        routerChapters = [
            f"{d.get('chapter')}({d.get('score')})"
            for d in (routing.get("candidate_chapter_details") or [])
            if isinstance(d, dict)
        ] or [str(c) for c in (routing.get("candidate_hs2") or [])]
        codeSets = bb.get("candidate_code_sets") or []
        latest = codeSets[-1] if isinstance(codeSets, list) and codeSets else {}
        classificationTrace = latest.get("classification_trace") if isinstance(latest, dict) else {}
        if not isinstance(classificationTrace, dict):
            classificationTrace = {}
        candidates = latest.get("candidates") if isinstance(latest, dict) else []
        cn8s = [_digits(c.get("cn8"))[:8] for c in (candidates or []) if isinstance(c, dict)]
        cn8s = [c for c in cn8s if len(c) == 8]
        return {
            "run_dir": str(runDirectory),
            "blackboard_path": str(store.bb_path),
            "understanding_mode": identity.get("understanding_mode"),
            "product_form_terms": identity.get("product_form_terms") or [],
            "chapter_hint_terms": identity.get("chapter_hint_terms") or [],
            "distilled_identity": {
                "commercial_identity": distilledIdentity.get("commercial_identity"),
                "product_form_signal_terms": distilledIdentity.get("product_form_signal_terms") or [],
                "processing_signal_terms": distilledIdentity.get("processing_signal_terms") or [],
            },
            "classification_trace": {
                "decision_status": classificationTrace.get("decision_status"),
                "traversal_status": classificationTrace.get("traversal_status"),
                "next_action": classificationTrace.get("next_action"),
                "backtracking_recommended": classificationTrace.get("backtracking_recommended"),
            },
            "translated_product_name": identity.get("translated_product_name"),
            "normalized_tariff_description": identity.get("normalized_tariff_description"),
            "llm_error": identity.get("llm_error"),
            "router_chapters": routerChapters,
            "cn8_candidates": cn8s,
            "errors": errors,
        }
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _recall(answer: str, cn8_candidates: list[str]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for name, width in RECALL_LEVELS:
        prefix = answer[:width]
        out[name] = bool(prefix) and any(c[:width] == prefix for c in cn8_candidates)
    return out


def main(arguments: list[str] | None = None) -> int:
    from bussiness_logic.document.document_pipeline import build_raw_input_from_ui

    args = ParseArguments(arguments)
    rows = LoadRows(args.csv_path, offset=args.offset, limit=args.limit)
    if not rows:
        print(f"no usable rows in {args.csv_path}")
        return 1

    agg = {"off": {n: 0 for n, _ in RECALL_LEVELS}, "on": {n: 0 for n, _ in RECALL_LEVELS}}
    results: list[JsonObject] = []
    for index, row in enumerate(rows):
        url, answer = row["url"], row["answer"]
        productId = f"row{args.offset + index}"
        print(f"\n### [{productId}] {url}\n    answer={answer}")
        try:
            rawInput = build_raw_input_from_ui(query=url, facts={"url": url})
        except Exception as exc:  # noqa: BLE001
            print(f"    ! scrape_failed: {type(exc).__name__}: {exc}")
            continue
        off = _run_chain(rawInput, productId=productId, use_llm=False, artifact_root=args.artifact_root)
        on = _run_chain(rawInput, productId=productId, use_llm=True, artifact_root=args.artifact_root)
        rOff, rOn = _recall(answer, off["cn8_candidates"]), _recall(answer, on["cn8_candidates"])
        for name, _ in RECALL_LEVELS:
            agg["off"][name] += int(rOff[name])
            agg["on"][name] += int(rOn[name])
        print(f"    OFF hs2={','.join(off['router_chapters'][:4])}")
        print(f"        food_form={off['food_form']!r:>16} recall={_fmt(rOff)} cn8={off['cn8_candidates'][:4]}")
        print(f"    ON  hs2={','.join(on['router_chapters'][:4])}")
        print(f"        food_form={on['food_form']!r:>16} recall={_fmt(rOn)} cn8={on['cn8_candidates'][:4]}"
              f"{'  llm_err=' + str(on['llm_error']) if on.get('llm_error') else ''}")
        if on.get("normalized_tariff_description"):
            print(f"        EN: {on['normalized_tariff_description']}")
        for err in (off["errors"] + on["errors"]):
            print(f"        ! {err}")
        results.append({"url": url, "answer": answer, "off": off, "on": on,
                        "recall_off": rOff, "recall_on": rOn})

    n = len(results)
    print(f"\n=== aggregate recall over {n} url(s) ===")
    for name, _ in RECALL_LEVELS:
        print(f"  {name}: OFF {agg['off'][name]}/{n}   ON {agg['on'][name]}/{n}")
    if args.summary_path:
        args.summary_path.parent.mkdir(parents=True, exist_ok=True)
        args.summary_path.write_text(
            json.dumps({"aggregate": agg, "rows": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"summary -> {args.summary_path}")
    return 0


def _fmt(recall: dict[str, bool]) -> str:
    return " ".join(f"{k}={'✓' if v else '✗'}" for k, v in recall.items())


if __name__ == "__main__":
    raise SystemExit(main())
