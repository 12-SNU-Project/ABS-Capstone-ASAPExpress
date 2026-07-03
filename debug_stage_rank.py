"""hs6 랭킹 법의학 — A(sibling-IDF)가 실데이터에서 무력화된 원인 추적.

최신 row0(llm_on) blackboard의 facts를 그대로 쓰고, DB에서 1602/1604/1605의
hs6 자식을 로드해 각 노드의 descr/incl 실물과, fact 토큰별로
[매칭됨 / IDF로 제거됨 / 미존재]를 출력한다. env 로드 후 실행:

  set -a; . ./.env; set +a
  conda run -n asap python debug_stage_rank.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agents.tools.staged_classification import (  # noqa: E402
    StagedClassificationTool, _tokens, LEVEL_AXES, LEVEL_AXIS_WEIGHTS,
)


def main() -> int:
    bb_path = sorted(glob.glob("artifacts/pipeline_llm_smoke/row0/llm_on/*/blackboard.json"))[-1]
    bb = json.load(open(bb_path))
    pu = bb.get("product_understanding") or {}
    product_facts = {
        "identity_lane": pu.get("identity_lane") or {},
        "composition_lane": pu.get("composition_lane") or {},
    }
    tool = StagedClassificationTool()
    facts = tool._read_facts(product_facts)
    children = tool._load_children(["1602", "1604", "1605"], 6)
    print(f"blackboard: {bb_path}\nhs6 children: {len(children)}개\n")

    # fact 토큰 → 가중치 (staged와 동일 계산)
    weights = LEVEL_AXIS_WEIGHTS["hs6"]
    token_weight: dict[str, float] = {}
    for axis in LEVEL_AXES["hs6"]:
        w = weights.get(axis, 1.0)
        for v in facts.get(axis, []):
            for tok in _tokens(v):
                if w > token_weight.get(tok, 0.0):
                    token_weight[tok] = w

    # doc_freq: descr만 vs descr+incl 두 가지로 계산해 비교
    df_descr: dict[str, int] = {}
    df_both: dict[str, int] = {}
    for row in children:
        t_descr = _tokens(row["descr"])
        t_both = t_descr | _tokens(row["incl"])
        for tok in t_descr & set(token_weight):
            df_descr[tok] = df_descr.get(tok, 0) + 1
        for tok in t_both & set(token_weight):
            df_both[tok] = df_both.get(tok, 0) + 1

    n = len(children)
    print(f"=== fact 토큰별 판별력 (형제 {n}명, 과반컷 {n//2}) ===")
    print(f"{'token':<16}{'w':>4}  {'df(descr)':>9}  {'df(descr+incl)':>14}  판정(현행=incl포함)")
    for tok, w in sorted(token_weight.items(), key=lambda x: -x[1]):
        d1, d2 = df_descr.get(tok, 0), df_both.get(tok, 0)
        verdict = "제거됨" if d2 * 2 > n else ("매칭무" if d2 == 0 else "생존")
        print(f"{tok:<16}{w:>4}  {d1:>9}  {d2:>14}  {verdict}")

    print("\n=== 관심 노드 실물 (descr / incl 앞부분) ===")
    for code in ("160555", "160556", "160420", "160231"):
        for row in children:
            if row["code"] == code:
                print(f"[{code}] descr: {str(row['descr'])[:70]}")
                print(f"         incl : {str(row['incl'])[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
