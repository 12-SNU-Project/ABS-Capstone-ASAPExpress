"""술어 테이블 커버리지 전수 감사 — '왜 질문이 이것밖에 없는가'의 실측.

설계 의도: 모든 분기점의 모든 형제 코드에 그 코드를 가르는 질문(조건)이
있어야 한다 (잔반 'Other'만 예외 — 형제 질문의 소거로 정의됨).
이 감사는 컴파일러를 dry로 돌려(테이블 무접촉·DB 무접속·.env 불필요)
코드 단위로 분류한다:

  discriminative  판별축 조건 보유 (product_identity 외 축 ≥1)
  identity_only   정체축(폴백 포함) 조건만
  bare            조건 0행 — 질문 자체가 없음
  residual        잔반(Other 계열) — bare여도 정상

PLAN Phase 0 확장 (2026-07-16):
  (a보강) bare 분기 전수 목록 — 원문 description + ancestor_conditions 동반
          (★중심 게이트: residual 제외 bare 분기 = 0)
  (b) product_identity 폴백 심층 — 값 명사의 std/vocab 등재율 × 형제 고유율
  (c) 정합 검사 — value 토큰이 source_text(정규화)에 전무한 행 + 상위 20
  (d) 자충수 배제 — not_contains 값이 수량·불용 토큰뿐인 행 전수
      (판정 세트는 컴파일러 픽스 B의 _QUANT_NEG_TOKENS를 import 공유 —
      픽스가 살아 있으면 이 목록은 구조적으로 0)

분모 주의: DB 무접속이라 cn_table allow 필터를 걸 수 없어 트리 전체가
분모다 (분기 98/960/1835 — 재컴파일 로그 96/957/1825의 상위집합, cn_table
밖 cn8 3,027개 포함분). 상위집합에서 bare=0이면 실 후보 공간도 bare=0.

산출: 콘솔 표 + DB/artifacts/decision_coverage_audit.json
실행: PYTHONPATH=src python DB/audit_decision_coverage.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

_RESIDUAL_RX = re.compile(r"^\s*other\b|^\s*others\b", re.I)


def main() -> int:
    from bussiness_logic.classification.offline.branch_decision_compiler import (
        _QUANT_NEG_TOKENS,
        _TOKEN,
        CompileGroupDecisions,
        _build_groups,
        _rows_from_tree,
        _stem,
    )

    def _norm_tokens(raw: str) -> set[str]:
        # 컴파일러 _toks와 같은 소문자+스템. 길이 필터는 안 둔다 — 스템 후
        # 3자 미만이 된 값 토큰이 원문에 있는데도 (c) 위반으로 오판 방지.
        return {_stem(t) for t in _TOKEN.findall(str(raw or "").lower())}

    def _vals(row: dict) -> list[str]:
        try:
            v = json.loads(row.get("value") or "null")
        except Exception:  # noqa: BLE001
            return []
        return [str(x) for x in v] if isinstance(v, list) else []

    tree_path = PROJECT_ROOT / "DB" / "artifacts" / "nomenclature_tree.jsonl"
    # DB 무접속: chapter_label은 표시용(그룹핑 무영향), allow=None은 트리
    # 전체 분모 — 도큐스트링의 '분모 주의' 참조.
    rows = _rows_from_tree(str(tree_path), None)
    groups = _build_groups(rows, {})

    # 트리 declarable 노드 — bare 목록의 원문 description/ancestor 원천
    decl: dict[str, dict] = {}
    with open(tree_path, encoding="utf-8") as f:
        for line in f:
            n = json.loads(line)
            if n.get("declarable"):
                decl[n["code10"]] = n

    def _tree_node(code: str) -> dict:
        return decl.get(str(code).ljust(10, "0")) or {}

    # ── dry 컴파일 전량 + 코드 단위 분류 (기존 골격) ──
    per_level: dict[str, Counter] = {}
    thin_branches: dict[str, list] = {}   # 형제 중 판별 보유가 0~1개인 분기
    axis_by_level: dict[str, Counter] = {}
    examples: dict[str, list] = {"bare": [], "identity_only": []}
    all_rows: list[dict] = []
    bare_branches: list[dict] = []        # ★게이트: 조건 0행 분기 (residual 제외)
    for level, parent, parent_label, members in groups:
        lvl = per_level.setdefault(level, Counter())
        axc = axis_by_level.setdefault(level, Counter())
        decision_rows = CompileGroupDecisions(level, parent, members)
        all_rows.extend(decision_rows)
        rows_by_code: dict[str, list] = {}
        for r in decision_rows:
            rows_by_code.setdefault(str(r.get("then_code") or ""), []).append(r)
            axc[str(r.get("cond_type") or "")] += 1
        discriminative_count = 0
        non_residual_codes = 0
        for code, label in members.items():
            code = str(code)
            label = str(label or "")
            # residual 판정은 컴파일러와 동일하게 leaf 세그먼트 기준 —
            # dash 헤더 경로에 낀 'Other'로 실 조건 코드를 잔반 오인 방지.
            residual = bool(_RESIDUAL_RX.match(label.rsplit(";", 1)[-1].strip()))
            non_residual_codes += not residual
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
        # (a보강) 분기 단위 bare: 조건 행 0 + 비잔반 형제 존재 → 원문 동반
        if not decision_rows and non_residual_codes:
            bare_branches.append({
                "level": level, "branch": parent, "branch_label": parent_label,
                "sibling_codes": sorted(members),
                "members": [{
                    "code": code, "label": str(label or ""),
                    "description": _tree_node(code).get("description", ""),
                    "ancestor_conditions": _tree_node(code).get(
                        "ancestor_conditions", []),
                } for code, label in sorted(members.items())],
            })
    bare_by_level = Counter(b["level"] for b in bare_branches)

    print("=== 코드 단위 커버리지 (트리 원천, dry — 테이블·DB 무접촉) ===")
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
    print(f"── ★게이트: bare 분기(조건 0행·비잔반 형제 보유) ──")
    print(f"  hs4 {bare_by_level.get('hs4', 0)} | hs6 {bare_by_level.get('hs6', 0)}"
          f" | cn8 {bare_by_level.get('cn8', 0)} | 총 {len(bare_branches)}"
          f" (0이어야 통과) | 총 조건 행 {len(all_rows)}")

    # ── (b) product_identity 폴백 심층 ──
    std_tokens: set[str] = set()
    with open(PROJECT_ROOT / "data" / "std_name_dictionary.jsonl",
              encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            for field in ("en", "spec_en"):
                v = str(rec.get(field) or "")
                if v and v.lower() != "nan":
                    std_tokens |= {t for t in _norm_tokens(v) if len(t) >= 3}

    vocab = json.loads((PROJECT_ROOT / "DB" / "artifacts" / "heading_vocab.json")
                       .read_text(encoding="utf-8"))
    _scope_cache: dict[tuple, set] = {}

    def _vocab_tokens(then_code: str) -> set[str]:
        # 등재 판정은 그 코드 자신의 chapter/heading/subheading 해설 스코프
        # 안에서만 — 전 텍스트 합집합이면 사실상 전부 등재로 나와 무의미.
        code = str(then_code)
        out: set[str] = set()
        for vocab_level, width in (("chapter", 2), ("heading", 4),
                                   ("subheading", 6)):
            if len(code) < width:
                continue
            key = (vocab_level, code[:width])
            if key not in _scope_cache:
                entry = (vocab.get(vocab_level) or {}).get(code[:width]) or {}
                toks: set[str] = set()
                for texts in entry.values():  # including / excluding
                    for t in texts or []:
                        toks |= {w for w in _norm_tokens(t) if len(w) >= 3}
                _scope_cache[key] = toks
            out |= _scope_cache[key]
        return out

    pid_rows = [r for r in all_rows
                if str(r["cond_type"]) == "product_identity"]
    owners: dict[tuple, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in pid_rows:
        gkey = (str(r["level"]), str(r["branch_id"]))
        for phrase in _vals(r):
            for t in phrase.split():
                owners[gkey][t].add(str(r["then_code"]))

    quad = Counter()
    tok_total = tok_std = tok_vocab = tok_unique = tok_named = 0
    quad_examples: dict[str, list] = {"named_candidate": [], "noise_candidate": []}
    for r in pid_rows:
        gkey = (str(r["level"]), str(r["branch_id"]))
        scoped = _vocab_tokens(str(r["then_code"]))
        toks = [t for phrase in _vals(r) for t in phrase.split()]
        if not toks:
            quad["empty_value"] += 1
            continue
        registered_any = unique_any = named_any = False
        for t in toks:
            in_std, in_vocab = t in std_tokens, t in scoped
            unique = len(owners[gkey][t]) == 1
            tok_total += 1
            tok_std += in_std
            tok_vocab += in_vocab
            tok_unique += unique
            if (in_std or in_vocab) and unique:
                tok_named += 1
                named_any = True
            registered_any = registered_any or in_std or in_vocab
            unique_any = unique_any or unique
        # named 후보 = 등재∧형제고유 토큰 보유 / 잡음 후보 = 둘 다 없음
        if named_any:
            cls = "named_candidate"
        elif registered_any:
            cls = "registered_shared"
        elif unique_any:
            cls = "unique_unregistered"
        else:
            cls = "noise_candidate"
        quad[cls] += 1
        if cls in quad_examples and len(quad_examples[cls]) < 10:
            quad_examples[cls].append({
                "level": r["level"], "branch_id": r["branch_id"],
                "then_code": r["then_code"], "value": _vals(r),
                "source_text": str(r.get("source_text") or "")[:100]})
    n_pid = len(pid_rows) or 1
    n_tok = tok_total or 1
    print(f"── (b) product_identity 폴백 심층 ({len(pid_rows)}행"
          f" = {len(pid_rows) / (len(all_rows) or 1) * 100:.1f}%) ──")
    print(f"  토큰 {tok_total} | std등재 {tok_std / n_tok * 100:.0f}%"
          f" | vocab등재 {tok_vocab / n_tok * 100:.0f}%"
          f" | 형제고유 {tok_unique / n_tok * 100:.0f}%"
          f" | 등재∧고유(named) {tok_named / n_tok * 100:.0f}%")
    for cls in ("named_candidate", "registered_shared",
                "unique_unregistered", "noise_candidate", "empty_value"):
        print(f"  행 {cls}: {quad.get(cls, 0)} ({quad.get(cls, 0) / n_pid * 100:.0f}%)")

    # ── (c) 정합 검사: value 토큰 ∩ source_text(정규화) = 공집합 행 ──
    c_violations = 0
    c_examples: list[dict] = []
    for r in all_rows:
        if str(r["op"]) == "quant_gate":
            continue  # value=null 설계 — 정합 검사 대상 아님
        value_toks = {t for phrase in _vals(r) for t in phrase.split()}
        if not value_toks or value_toks & _norm_tokens(r.get("source_text")):
            continue
        c_violations += 1
        if len(c_examples) < 20:
            c_examples.append({
                "level": r["level"], "branch_id": r["branch_id"],
                "then_code": r["then_code"], "cond_type": r["cond_type"],
                "op": r["op"], "value": _vals(r),
                "source_text": str(r.get("source_text") or "")})
    print(f"── (c) 값↔원문 정합 위반: {c_violations}행 ──")

    # ── (d) 자충수 배제: not_contains 값이 수량·불용 토큰뿐인 행 전수 ──
    d_rows: list[dict] = []
    for r in all_rows:
        if str(r["op"]) != "not_contains":
            continue
        toks = [t for phrase in _vals(r) for t in phrase.split()]
        if toks and all(t in _QUANT_NEG_TOKENS for t in toks):
            d_rows.append({
                "level": r["level"], "branch_id": r["branch_id"],
                "then_code": r["then_code"], "value": _vals(r),
                "source_text": str(r.get("source_text") or "")})
    print(f"── (d) 수량·불용 토큰만의 not_contains: {len(d_rows)}행 ──")

    out = {
        "meta": {
            "basis": "dry compile — 테이블·DB 무접촉, allow 필터 없음"
                     " (트리 전체 분모 = 재컴파일 로그 96/957/1825의 상위집합;"
                     " cn_table 밖 cn8 포함. CNEN 행은 DB 원천이라 dry 범위 밖)",
            "total_rows": len(all_rows),
            "definitions": {
                "bare_branch": "조건 행 0개 + 비잔반 형제 ≥1 분기 — ★게이트 0",
                "b_registered": "값 토큰이 std_name_dictionary(en/spec_en) 또는"
                                " 자기 chapter/heading/subheading heading_vocab"
                                " 텍스트에 등장 (스템 정규화)",
                "b_unique": "같은 (level, branch_id)의 product_identity 값 중"
                            " 해당 토큰 보유 then_code가 1개뿐",
                "c_violation": "op≠quant_gate 행에서 value 토큰이 정규화된"
                               " source_text에 하나도 등장하지 않음",
                "d_selfdefeat": "not_contains 값 토큰 전부가 컴파일러"
                                " _QUANT_NEG_TOKENS(수량·불용)에 포함",
            },
        },
        "per_level": {k: dict(v) for k, v in per_level.items()},
        "axis_by_level": {k: dict(v) for k, v in axis_by_level.items()},
        "thin_branch_examples": thin_branches,
        "class_examples": examples,
        "a_bare_branches": {
            "per_level": dict(bare_by_level),
            "total": len(bare_branches),
            "branches": bare_branches,
        },
        "b_fallback_deep_dive": {
            "rows": len(pid_rows),
            "token_stats": {
                "total": tok_total, "std_registered": tok_std,
                "vocab_registered": tok_vocab, "sibling_unique": tok_unique,
                "registered_and_unique": tok_named,
            },
            "row_classes": dict(quad),
            "examples": quad_examples,
        },
        "c_value_source_mismatch": {
            "count": c_violations, "top_examples": c_examples,
        },
        "d_selfdefeating_exclusions": {
            "count": len(d_rows), "rows": d_rows,
        },
    }
    out_path = PROJECT_ROOT / "DB" / "artifacts" / "decision_coverage_audit.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
