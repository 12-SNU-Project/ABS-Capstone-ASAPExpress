"""P4 홀드아웃 스모크 — food_import_testset_labeled.csv (물품명 기반, URL 없음).

kurly_market_smoke와 달리 스크래핑/OCR 없이 CSV의 텍스트 필드로 raw input을
직접 구성해 기존 컴포넌트 체인(EvidenceIntake -> ProductUnderstanding ->
Hs2Routing -> Classification)을 그대로 태운다. 별도 분류 로직 없음.

입력 필드 -> raw input 매핑:
  korean_name                -> product_name
  english_name + rag 서술    -> description + reconstructed_fact_texts
  main_ingredients_original  -> 원재료명 fact (조성 답안지)

채점: asap_x_hs6 기준 hs2/hs4/hs6 (existing_hs6는 참고 병기).
합성/이름 기반 한계로 hs6은 참고치, 주지표는 hs4 top1.

실행 (conda asap, 런타임 env):
  PYTHONPATH=src python holdout_smoke.py --limit 50            # 파일럿
  PYTHONPATH=src python holdout_smoke.py --offset 50 --limit 200
  PYTHONPATH=src python holdout_smoke.py --limit 0             # 전량 (1,045건 — LLM 비용 주의)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = PROJECT_ROOT / "data" / "food_import_testset_labeled.csv"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "holdout-smoke"
LEVELS = (("hs2", 2), ("hs4", 4), ("hs6", 6))


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def build_raw_input(row: dict[str, str]) -> dict:
    name = (row.get("korean_name") or "").strip()
    english = (row.get("english_name_original") or "").strip()
    rag = (row.get("product_input_for_rag") or "").strip()
    ingredients = (row.get("main_ingredients_original") or "").strip()
    # kurly 유래 행은 rag/원재료 컬럼이 비어 있고 kurly_* 컬럼이 서술을 담는다
    # (미매핑 시 이름만 입력돼 identity 공백 도미노 — 1,002행 후보 0 실측)
    kurly_desc = (row.get("kurly_short_description") or "").strip()
    kurly_keyword = (row.get("kurly_keyword") or "").strip()
    fact_texts = [t for t in (english, rag, kurly_desc) if t]
    facts = []
    if kurly_keyword:
        facts.append({"field_name": "키워드", "value": kurly_keyword})
        fact_texts.append(f"키워드: {kurly_keyword}")
    if ingredients:
        facts.append({"field_name": "원재료명", "value": ingredients})
        fact_texts.append(f"원재료명: {ingredients}")
    return {
        "product_name": name,
        "description": rag or english or kurly_desc,
        "reconstructed_fact_texts": fact_texts,
        "reconstructed_product_facts": facts,
        "source_urls": [],
    }


def run_chain(raw_input: dict, run_dir: Path) -> list[str]:
    from agents.blackboard import BlackboardStore
    from agents.pipeline_components import (
        ClassificationComponent,
        EvidenceIntakeComponent,
        Hs2RoutingComponent,
        ProductUnderstandingComponent,
    )

    store = BlackboardStore.create(
        runtime_mode="smoke", run_id="run_001",
        run_dir=run_dir, validate_on_write=False,
    )
    for component in (
        EvidenceIntakeComponent(raw_input),
        ProductUnderstandingComponent(),
        Hs2RoutingComponent(),
        ClassificationComponent(),
    ):
        result = component.Execute(store)
        if not result.success:
            return []
    bb = store.load()
    code_sets = bb.get("candidate_code_sets") or []
    latest = code_sets[-1] if code_sets else {}
    return [
        _digits(c.get("cn8"))[:8]
        for c in (latest.get("candidates") or [])
        if _digits(c.get("cn8"))
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-path", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    rows = list(csv.DictReader(open(args.csv_path, encoding="utf-8-sig")))
    # 라벨: asap_x_hs6(전문가 교정, 43건) 우선, 없으면 existing_hs6 (kurly 1,002건).
    # existing은 기존 코드라 라벨 노이즈 가능 — 집계에 소스별 분리 병기.
    for r in rows:
        r["_answer"] = _digits(r.get("asap_x_hs6"))[:6] or _digits(r.get("existing_hs6"))[:6]
        r["_label_src"] = "asap_x" if _digits(r.get("asap_x_hs6")) else "existing"
    rows = [r for r in rows if r["_answer"]]
    # 튜닝셋(22건 kurly URL) 중복 제외 — 홀드아웃은 처음 보는 시험지여야 한다
    tuning_pids = set()
    tuning_csv = PROJECT_ROOT / "data" / "EU_HS_test.csv"
    if tuning_csv.exists():
        for tr in csv.DictReader(open(tuning_csv, encoding="utf-8-sig")):
            m = re.search(r"(m\d{8,})", str(tr.get("상품 상세") or ""))
            if m:
                tuning_pids.add(m.group(1).lower())
    before = len(rows)
    def _pid(r):
        m = re.search(r"(m\d{8,})", str(r.get("kurly_url") or "") + str(r.get("master_code") or ""), re.I)
        return m.group(1).lower() if m else ""
    rows = [r for r in rows if _pid(r) not in tuning_pids]
    print(f"튜닝셋 중복 제외: {before - len(rows)}건")
    rows = rows[args.offset:]
    if args.limit:
        rows = rows[: args.limit]
    print(f"홀드아웃 {len(rows)}건 (offset={args.offset})")

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    agg = {name: Counter() for name, _ in LEVELS}
    agg_existing = {name: Counter() for name, _ in LEVELS}
    results = []
    per_src = {"asap_x": {n: Counter() for n, _ in LEVELS},
               "existing": {n: Counter() for n, _ in LEVELS}}
    src_n = Counter()
    for index, row in enumerate(rows):
        answer = row["_answer"].zfill(6)
        existing = _digits(row.get("existing_hs6"))[:6].zfill(6)
        name = (row.get("korean_name") or "?")[:30]
        run_dir = ARTIFACT_ROOT / stamp / f"row{args.offset + index}"
        try:
            candidates = run_chain(build_raw_input(row), run_dir)
        except Exception as error:  # noqa: BLE001
            print(f"  ! {name}: {type(error).__name__}: {error}")
            candidates = []
        marks = []
        src = row["_label_src"]
        src_n[src] += 1
        for level, width in LEVELS:
            top1 = bool(candidates) and candidates[0][:width] == answer[:width]
            top3 = any(c[:width] == answer[:width] for c in candidates[:3])
            agg[level]["top1"] += int(top1)
            agg[level]["top3"] += int(top3)
            per_src[src][level]["top1"] += int(top1)
            per_src[src][level]["top3"] += int(top3)
            agg_existing[level]["top1"] += int(
                bool(candidates) and candidates[0][:width] == existing[:width])
            marks.append("O" if top1 else ("o" if top3 else "X"))
        results.append({"name": name, "answer": answer, "existing": existing,
                        "candidates": candidates[:3], "marks": marks})
        print(f"  [{args.offset + index}] {'/'.join(marks)} {name} 답={answer} top1={candidates[0] if candidates else '-'}")
    n = len(results)
    print(f"\n=== 홀드아웃 집계 ({n}건, 라벨: asap_x 우선/없으면 existing) ===")
    for level, _ in LEVELS:
        t1, t3 = agg[level]["top1"], agg[level]["top3"]
        print(f"  {level}: top1 {t1}/{n} ({t1 / n * 100:.0f}%)  top3 {t3}/{n} ({t3 / n * 100:.0f}%)")
    for src in ("asap_x", "existing"):
        m = src_n[src]
        if not m:
            continue
        parts = []
        for level, _ in LEVELS:
            t1 = per_src[src][level]["top1"]
            parts.append(f"{level} {t1}/{m} ({t1 / m * 100:.0f}%)")
        print(f"  [{src} 라벨 {m}건] top1: {'  '.join(parts)}")
    out = ARTIFACT_ROOT / stamp / "holdout-summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"n": n, "results": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"summary -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
