"""골든 DTO 스모크 — 지각(PU/LLM/OCR) 완전 분리, 바인딩 층 단위 테스트.

가정: composition/identity lane이 완벽 충전됐다(data/golden_dto_22.json,
설계자 검수본). 그 위에서 라우팅+staged만 돌린다 — LLM 0콜, 초 단위 실행.
여기서 틀리는 것은 전부 질문(사이드카)·바인딩·매칭의 결함이다:

  6/8 검증 목표 = "각 분류 기준 질문이 그 답을 가진 DTO 필드에 연결되는가"

실행:
  PYTHONPATH=src python golden_dto_smoke.py            # 전체
  PYTHONPATH=src python golden_dto_smoke.py --pid 5037259   # 단품
  PYTHONPATH=src python golden_dto_smoke.py --detail        # 미결 조건 상세
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
GOLDEN = PROJECT_ROOT / "data" / "golden_dto_22.json"
LEVELS = (("hs2", 2), ("hs4", 4), ("hs6", 6), ("cn8", 8))


def _digits(v):
    return re.sub(r"\D", "", str(v or ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", default="")
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from agents.tools.chapter_index_repository import LoadPreClassificationChapterRows
    from agents.tools.pre_classification_router import (
        BuildPreClassificationRouteInput,
        PreClassificationDomainRouter,
    )
    from agents.tools.staged_classification import StagedClassificationTool

    golden = json.load(open(GOLDEN, encoding="utf-8"))
    if args.pid:
        golden = {k: v for k, v in golden.items() if k == args.pid}

    agg = {lvl: Counter() for lvl, _ in LEVELS}
    todo_products = []
    for pid, g in sorted(golden.items()):
        if "TODO" in json.dumps(g, ensure_ascii=False):
            todo_products.append(str(g.get("product_name"))[:14])
        ih = g["identity_hints"]
        cf = g["composition_facts"]
        product_facts = {"identity_hints": ih, "composition_facts": cf}
        ans = _digits(g["answer"])[:8].ljust(8, "0")

        def st(v):
            if isinstance(v, str):
                return (v.strip(),) if v.strip() and "TODO" not in v else ()
            return tuple(str(x).strip() for x in (v or []) if str(x).strip() and "TODO" not in str(x))

        route_input = BuildPreClassificationRouteInput(
            productName=str(g.get("product_name") or ""),
            shortDescription="",
            factTexts=(
                str(ih.get("normalized_tariff_description") or ""),
                *st(ih.get("identity_terms")),
                *st(ih.get("product_form_terms")),
            ),
            structuredProductFacts=[],
            processingState=str(ih.get("processing_state") or ""),
            containsSauceOrBroth=(
                bool(cf.get("contains_sauce_or_broth"))
                if isinstance(cf.get("contains_sauce_or_broth"), bool) else None
            ),
        )
        hint = PreClassificationDomainRouter(
            chapterRowsProvider=LoadPreClassificationChapterRows,
        ).Route(route_input)
        routing = {
            "allowed_hs2": list(hint.candidateHs2),
            "candidate_chapter_details": list(hint.candidateChapterDetails),
        }
        staged = StagedClassificationTool().classify(
            product_facts=product_facts,
            routing_context=routing,
        )
        cands = [_digits(c.get("cn8"))[:8] for c in (staged.get("candidates") or [])]
        marks = []
        for lvl, w in LEVELS:
            if len(_digits(g["answer"])) < w:
                marks.append("·")
                continue
            top1 = bool(cands) and cands[0][:w] == ans[:w]
            agg[lvl]["top1"] += int(top1)
            agg[lvl]["n"] += 1
            marks.append("O" if top1 else "X")
        print(f"  {'/'.join(marks):<8} {str(g.get('product_name'))[:22]:<24} 답={ans[:6]} top1={cands[0][:6] if cands else '-'}")

        if args.detail:
            for stg in staged.get("stages") or []:
                lvl = stg.get("stage")
                entry = next((r for r in stg.get("candidates_considered") or []
                              if ans.startswith(str(r.get("code")))), None)
                if entry:
                    for d in entry.get("decision_detail") or []:
                        if d.get("verdict") == "undecided":
                            print(f"      [{lvl}] 정답조건 미결: {d.get('cond')} {d.get('value')} why={d.get('why')}")

    print("\n=== 골든 DTO (지각 완전 가정) — 바인딩 층 상한선 ===")
    for lvl, _ in LEVELS:
        n, t1 = agg[lvl]["n"], agg[lvl]["top1"]
        if n:
            print(f"  {lvl}: top1 {t1}/{n} ({t1 / n * 100:.0f}%)")
    if todo_products:
        print(f"\n⚠ TODO 검수 미완 제품 {len(todo_products)}개 (충전 가정 미충족 — 수치 왜곡):")
        print("  ", ", ".join(todo_products))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
