"""EU_HS정답코드.xlsx 스모크 — URL 없이 제품명+주성분으로 전 체인 실행.

컬럼 매핑 (헤더 2행째):
  제품명(B)          -> product_name
  제품명 EN(C)       -> description + fact_texts
  Main Ingredients(D)-> 원재료명 fact (조성 답안지)
  EU HS CODE(E)      -> 정답 (10자리, hs2/hs4/hs6/cn8 채점)

US 비교·판정 사유 컬럼은 입력에 넣지 않는다 (정답 유출 방지).
튜닝 22건(kurly)과 이름이 겹치는 행은 ⚠튜닝겹침으로 표시하고 분리 집계 —
겹침 행은 "본 적 있는 시험지"라 일반화 증거로 못 쓴다.

실행:
  PYTHONPATH=src python eu50_smoke.py --limit 10   # 파일럿
  PYTHONPATH=src python eu50_smoke.py --limit 0    # 전량
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_XLSX = PROJECT_ROOT / "data" / "EU_HS정답코드.xlsx"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "eu50-smoke"
LEVELS = (("hs2", 2), ("hs4", 4), ("hs6", 6), ("cn8", 8))


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _norm_name(name: str) -> str:
    return re.sub(r"[\s\[\]()*\xa0]+", "", str(name or "")).lower()


def _tuning_names() -> set[str]:
    """kurly 22건 제품명 — 최신 스모크 summary에서 수집 (없으면 빈 셋)."""
    path = PROJECT_ROOT / "artifacts" / "kurly-market-smoke" / "runtime-smoke-summary.json"
    names: set[str] = set()
    try:
        for item in json.load(open(path)):
            name = str((item.get("product") or {}).get("product_name") or "")
            if name:
                names.add(_norm_name(name))
    except Exception:  # noqa: BLE001
        pass
    return names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx-path", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    import pandas as pd

    from holdout_smoke import run_chain  # 동일 컴포넌트 체인 재사용

    df = pd.read_excel(args.xlsx_path, header=2)  # 3행째가 헤더 (1~2행은 유의사항)
    col = {c: str(c) for c in df.columns}
    def pick(*keys):
        for c in df.columns:
            if any(k in str(c) for k in keys):
                return c
        raise KeyError(keys)
    c_name, c_en = pick("제품명"), pick("EN", "(EN)")
    c_ing, c_ans = pick("Ingredient"), pick("EU HS")

    tuning = _tuning_names()
    rows = []
    for _, r in df.iterrows():
        name = str(r.get(c_name) or "").replace("\xa0", " ").strip()
        answer = _digits(r.get(c_ans))[:8]
        if not name or name == "nan" or len(answer) < 6:
            continue
        rows.append({
            "name": name,
            "english": str(r.get(c_en) or "").strip(),
            "ingredients": str(r.get(c_ing) or "").strip(),
            "answer": answer.ljust(8, "0")[:8],
            "seen": _norm_name(name) in tuning,
        })
    print(f"유효 {len(rows)}건 (튜닝 22건과 이름 겹침: {sum(1 for x in rows if x['seen'])}건 — 분리 집계)")
    rows = rows[args.offset:]
    if args.limit:
        rows = rows[: args.limit]

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    agg = {"전체": {n: Counter() for n, _ in LEVELS},
           "신규": {n: Counter() for n, _ in LEVELS},
           "겹침": {n: Counter() for n, _ in LEVELS}}
    n_by = Counter()
    results = []
    for index, row in enumerate(rows):
        english = row["english"] if row["english"].lower() != "nan" else ""
        ingredients = row["ingredients"] if row["ingredients"].lower() != "nan" else ""
        fact_texts = [t for t in (english,) if t]
        facts = []
        if ingredients:
            facts.append({"field_name": "원재료명", "value": ingredients})
            fact_texts.append(f"원재료명: {ingredients}")
        raw_input = {
            "product_name": row["name"],
            "description": english,
            "reconstructed_fact_texts": fact_texts,
            "reconstructed_product_facts": facts,
            "source_urls": [],
        }
        run_dir = ARTIFACT_ROOT / stamp / f"row{args.offset + index}"
        try:
            candidates = run_chain(raw_input, run_dir)
        except Exception as error:  # noqa: BLE001
            print(f"  ! {row['name'][:24]}: {type(error).__name__}: {error}")
            candidates = []
        bucket = "겹침" if row["seen"] else "신규"
        n_by["전체"] += 1
        n_by[bucket] += 1
        marks = []
        for level, width in LEVELS:
            top1 = bool(candidates) and candidates[0][:width] == row["answer"][:width]
            top3 = any(c[:width] == row["answer"][:width] for c in candidates[:3])
            for scope in ("전체", bucket):
                agg[scope][level]["top1"] += int(top1)
                agg[scope][level]["top3"] += int(top3)
            marks.append("O" if top1 else ("o" if top3 else "X"))
        results.append({**row, "candidates": candidates[:3], "marks": marks})
        flag = " ⚠튜닝겹침" if row["seen"] else ""
        print(f"  [{args.offset + index}] {'/'.join(marks)} {row['name'][:26]} 답={row['answer']}"
              f" top1={candidates[0] if candidates else '-'}{flag}")

    print(f"\n=== EU50 스모크 ({n_by['전체']}건) ===")
    for scope in ("전체", "신규", "겹침"):
        m = n_by[scope]
        if not m:
            continue
        parts = []
        for level, _ in LEVELS:
            t1 = agg[scope][level]["top1"]
            parts.append(f"{level} {t1}/{m}({t1 / m * 100:.0f}%)")
        print(f"  [{scope} {m}건] top1: {'  '.join(parts)}")
    out = ARTIFACT_ROOT / stamp / "eu50-summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"n": n_by["전체"], "results": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"summary -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
