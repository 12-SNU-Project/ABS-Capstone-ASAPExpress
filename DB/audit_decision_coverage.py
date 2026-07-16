"""술어 테이블 커버리지 전수 감사 — '왜 질문이 이것밖에 없는가'의 실측.

설계 의도: 모든 분기점의 모든 형제 코드에 그 코드를 가르는 질문(조건)이
있어야 한다 (잔반 'Other'만 예외 — 형제 질문의 소거로 정의됨).
이 감사는 컴파일러를 dry로 돌려(테이블 무접촉) 코드 단위로 분류한다:

  discriminative  판별축 조건 보유 (product_identity 외 축 ≥1)
  identity_only   정체축(폴백 포함) 조건만
  bare            조건 0행 — 질문 자체가 없음
  residual        잔반(Other 계열) — bare여도 정상

산출: 콘솔 표 + DB/artifacts/decision_coverage_audit.json
실행: PYTHONPATH=src python DB/audit_decision_coverage.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

_RESIDUAL_RX = re.compile(r"^\s*other\b|^\s*others\b", re.I)


def main() -> int:
    from sqlalchemy import text

    from bussiness_logic.classification.offline.branch_decision_compiler import (
        CompileGroupDecisions,
        _build_groups,
        _rows_from_tree,
    )
    from db.db_session_manager import DbSessionManager

    manager = DbSessionManager.GetInstance()
    chapter_label: dict[str, str] = {}
    # 컴파일러 본체(_main:423)는 title/description 컬럼을 SELECT하다 실패를
    # 삼키고 chapter_label 공란으로 돌았다(실컬럼 chapter_title — 부차 발견,
    # 원장 기록 대상). 감사는 실컬럼으로 정확히 읽는다.
    for row in manager.FetchRows(text(
            'SELECT chapter, chapter_title FROM "cn_chapter_index"'), {}):
        d = dict(row)
        ch = re.sub(r"\D", "", str(d.get("chapter") or ""))[:2].zfill(2)
        if ch:
            chapter_label[ch] = str(d.get("chapter_title") or "")[:200]
    allow = {str(dict(r).get("cn8") or "") for r in manager.FetchRows(
        text("SELECT cn8 FROM cn_table"), {})}
    tree_path = str(PROJECT_ROOT / "DB" / "artifacts" / "nomenclature_tree.jsonl")
    rows = _rows_from_tree(tree_path, allow)
    groups = _build_groups(rows, chapter_label)

    per_level: dict[str, Counter] = {}
    thin_branches: dict[str, list] = {}   # 형제 중 판별 보유가 0~1개인 분기
    axis_by_level: dict[str, Counter] = {}
    examples: dict[str, list] = {"bare": [], "identity_only": []}
    for level, parent, _pl, members in groups:
        lvl = per_level.setdefault(level, Counter())
        axc = axis_by_level.setdefault(level, Counter())
        decision_rows = CompileGroupDecisions(level, parent, members)
        rows_by_code: dict[str, list] = {}
        for r in decision_rows:
            rows_by_code.setdefault(str(r.get("then_code") or ""), []).append(r)
            axc[str(r.get("cond_type") or "")] += 1
        discriminative_count = 0
        for code, label in members.items():
            code = str(code)
            label = str(label or "")
            residual = bool(_RESIDUAL_RX.match(label))
            conds = rows_by_code.get(code, [])
            axes = {str(c.get("cond_type") or "") for c in conds}
            if axes - {"product_identity"}:
                cls = "discriminative"
                discriminative_count += 1
            elif axes:
                cls = "identity_only"
            else:
                cls = "residual_bare" if residual else "bare"
            lvl[cls] += 1
            lvl["codes"] += 1
            if cls in examples and len(examples[cls]) < 8:
                examples[cls].append(
                    {"level": level, "code": code, "label": label[:70]})
        lvl["branches"] += 1
        if discriminative_count <= 1 and len(members) >= 2:
            lvl["tie_prone_branches"] += 1
            if len(thin_branches.setdefault(level, [])) < 6:
                thin_branches[level].append(
                    {"parent": parent, "siblings": len(members),
                     "discriminative": discriminative_count})

    print("=== 코드 단위 커버리지 (트리 원천, dry — 테이블 무접촉) ===")
    for level in ("hs4", "hs6", "cn8"):
        c = per_level.get(level, Counter())
        n = c["codes"] or 1
        print(f"  {level}: 코드 {c['codes']} | 판별 {c['discriminative']}"
              f" ({c['discriminative']/n*100:.0f}%) | 정체만 {c['identity_only']}"
              f" ({c['identity_only']/n*100:.0f}%) | 잔반 {c['residual_bare']}"
              f" | 무조건(bare) {c['bare']} ({c['bare']/n*100:.0f}%)")
        print(f"       분기 {c['branches']}개 중 판별 형제 ≤1 (동점 취약):"
              f" {c['tie_prone_branches']}개"
              f" ({c['tie_prone_branches']/(c['branches'] or 1)*100:.0f}%)")
    out = {
        "per_level": {k: dict(v) for k, v in per_level.items()},
        "axis_by_level": {k: dict(v) for k, v in axis_by_level.items()},
        "thin_branch_examples": thin_branches,
        "class_examples": examples,
    }
    out_path = PROJECT_ROOT / "DB" / "artifacts" / "decision_coverage_audit.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
