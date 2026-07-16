"""US_KR_test.xlsx 홀드아웃 스모크 — 전 품목, 품목명만(name-only), hs6 채점.

HS는 6자리까지 WCO 공통이므로 '한국 HS Code'[:6]을 정답으로 사용한다.
'미국 HS Code'[:6]과 불일치하는 행은 개정 시차/라벨 모호 가능성으로 표시.
'비고' 컬럼은 코드 정보를 포함하므로 입력에 넣지 않는다 (정답 유출 방지).

입력은 품목명 하나뿐 — 식품 홀드아웃(관세 서술+원재료 포함)보다 훨씬 얇고,
비식품 챕터는 llm-v1 술어가 없어 lexical+결정테이블로만 돈다. 기대치는
보수적으로: 주지표 hs4, hs6은 참고.

실행:
  PYTHONPATH=src python uskr_smoke.py --limit 30     # 파일럿
  PYTHONPATH=src python uskr_smoke.py --limit 0      # 전량 146건
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_XLSX = PROJECT_ROOT / "data" / "US_KR_test.xlsx"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "uskr-smoke"
LEVELS = (("hs2", 2), ("hs4", 4), ("hs6", 6))


def _digits(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    # 엑셀 숫자셀은 선행 0을 잃는다 (0303.83-0000 -> 303830000, 9자리).
    # 홀수 자릿수면 앞에 0을 복원 — 01~09류가 30~98류로 둔갑하는 것 방지.
    if len(digits) in (5, 7, 9):
        digits = "0" + digits
    return digits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx-path", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    import pandas as pd

    from holdout_smoke import run_chain  # 동일 컴포넌트 체인 재사용

    df = pd.read_excel(args.xlsx_path)
    rows = []
    for _, r in df.iterrows():
        name = str(r.get("품목 분류 명칭") or "").strip()
        kr = _digits(r.get("한국 HS Code"))[:6]
        us = _digits(r.get("미국 HS Code"))[:6]
        if name and len(kr) == 6:
            rows.append({"name": name, "answer": kr, "us6": us})
    print(f"유효 행 {len(rows)} (한·미 hs6 불일치: {sum(1 for r in rows if r['us6'] and r['us6'] != r['answer'])}건 — 라벨 모호 후보)")
    rows = rows[args.offset:]
    if args.limit:
        rows = rows[: args.limit]

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    agg = {name: Counter() for name, _ in LEVELS}
    results = []
    for index, row in enumerate(rows):
        raw_input = {
            "product_name": row["name"],
            "description": "",
            "reconstructed_fact_texts": [row["name"]],
            "reconstructed_product_facts": [],
            "source_urls": [],
        }
        run_dir = ARTIFACT_ROOT / stamp / f"row{args.offset + index}"
        try:
            candidates = run_chain(raw_input, run_dir)
        except Exception as error:  # noqa: BLE001
            print(f"  ! {row['name'][:24]}: {type(error).__name__}: {error}")
            candidates = []
        marks = []
        for level, width in LEVELS:
            top1 = bool(candidates) and candidates[0][:width] == row["answer"][:width]
            top3 = any(c[:width] == row["answer"][:width] for c in candidates[:3])
            agg[level]["top1"] += int(top1)
            agg[level]["top3"] += int(top3)
            marks.append("O" if top1 else ("o" if top3 else "X"))
        ambiguous = " ⚠kr≠us" if row["us6"] and row["us6"] != row["answer"] else ""
        results.append({**row, "candidates": candidates[:3], "marks": marks})
        print(f"  [{args.offset + index}] {'/'.join(marks)} {row['name'][:26]} 답={row['answer']}"
              f" top1={candidates[0] if candidates else '-'}{ambiguous}")
    n = len(results)
    print(f"\n=== US_KR 홀드아웃 ({n}건, 전 품목·name-only, 한국HS6 기준) ===")
    for level, _ in LEVELS:
        t1, t3 = agg[level]["top1"], agg[level]["top3"]
        print(f"  {level}: top1 {t1}/{n} ({t1 / n * 100:.0f}%)  top3 {t3}/{n} ({t3 / n * 100:.0f}%)")
    out = ARTIFACT_ROOT / stamp / "uskr-summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"n": n, "results": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"summary -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
