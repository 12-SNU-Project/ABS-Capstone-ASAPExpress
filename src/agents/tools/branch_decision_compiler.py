"""Branch DECISION-TABLE compiler (offline, deterministic parser — no LLM).

The designer model this implements: classification is not scoring but a
walk of legal condition checks — at every branching point, compare the
description's CONDITION against a specific ProductUnderstandingFacts field;
met -> that code, not met -> next line, nothing met -> "Other" (the else
branch). Repeated per level (hs4 -> hs6 -> cn8).

This compiler reads cn_table branch groups (parent label + sibling labels)
and emits one condition row per (code, condition) into the LEAN sidecar
``branch_decision_index``:

  level, branch_id(parent), seq(legal check order = code order),
  then_code, cond_type, dto_field, op, value(JSON), source_text, version

No unit/severity/confidence/predicate_id sprawl — a condition either parses
deterministically or is not emitted (the lexical engine remains the
fallback for unparsed branches). "Other" lines emit nothing: else is
implicit in elimination.

Usage:
  PYTHONPATH=src python -m agents.tools.branch_decision_compiler                 # audit
  PYTHONPATH=src python -m agents.tools.branch_decision_compiler --apply
  PYTHONPATH=src python -m agents.tools.branch_decision_compiler --chapters 16,19 --apply
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import csv

from agents.tools.cn_predicate_llm_compiler import _build_groups, _toks

# ── 기준 유형 taxonomy (7/2 설계 사양서) ─────────────────────────────
# data/classification_criterion_taxonomy_20260702.csv 가 유일한 축 정의다:
# criterion_type + 탐지 정규식(examples) + role. 손으로 재발명했던 7축
# (species/form/... )은 이 16유형의 부분집합이라 폐기.
_TAXONOMY_CSV = Path(__file__).resolve().parents[3] / "data" / "classification_criterion_taxonomy_20260702.csv"

# criterion_type -> 질문에 답할 DTO 필드 (없는 유형은 미결로 남는 게 정직)
CRITERION_FIELD_BINDING = {
    "product_identity": (
        # food_form 추가: 'noodle/rice cake' 같은 판별형 typed 값이 identity
        # 질문의 정답 필드인데 빠져 있었다 — 칼국수 1902 확정 불가 실측.
        "identity_hints.normalized_tariff_description;identity_hints.identity_terms;"
        "identity_hints.food_form;identity_hints.ingredient_class;"
        "composition_facts.principal_ingredient"
    ),
    "species_source": (
        # principal_ingredient_guess 선두: 주성분(성분 서열 1위)이 종 질문의
        # 1차 답안. typed 확정 자격은 없음(LLM 추론 단독 확정 금지) — 증거 가산만.
        "identity_hints.principal_ingredient_guess;"
        "identity_hints.normalized_tariff_description;identity_hints.identity_terms;"
        "identity_hints.ingredient_class;composition_facts.ingredient_classes;"
        "composition_facts.principal_ingredient"
    ),
    "material_composition": (
        "identity_hints.normalized_tariff_description;identity_hints.identity_terms;"
        "composition_facts.ingredient_classes;composition_facts.principal_ingredient;"
        "composition_facts.composition_terms"
    ),
    "preservation_state": "identity_hints.processing_state;identity_hints.product_form_terms",
    "processing_method": "identity_hints.processing_state;composition_facts.processing_state;identity_hints.product_form_terms",
    "physical_form": (
        "identity_hints.food_form;identity_hints.product_form_terms;"
        "composition_facts.contains_wrapper_or_dough;composition_facts.contains_sauce_or_broth"
    ),
    "quantitative_threshold": "composition_facts.ingredient_percentages",
    "exclusion_boundary": "*tokens*",
    # 아래 유형들은 현 DTO에 답 필드가 없다 — 조건은 컴파일하되 런타임에서
    # 미결(undecided)로 남는 것이 정직한 동작 (답안지 백로그의 유형별 목록)
    "packaging_presentation": "identity_hints.product_form_terms",
    "dimension_capacity": "composition_facts.ingredient_percentages",
    "intended_use_function": "identity_hints.normalized_tariff_description;identity_hints.identity_terms",
    "technical_specification": "identity_hints.normalized_tariff_description",
    "parts_accessories": "identity_hints.normalized_tariff_description;identity_hints.identity_terms",
    "condition_quality": "identity_hints.processing_state;identity_hints.normalized_tariff_description",
    "demographic_target": "identity_hints.normalized_tariff_description;identity_hints.identity_terms",
}

_COND_CLAUSE = re.compile(r"whether\s+or\s+not[^,;.)]*", re.I)
_NEG_VALUE = re.compile(
    r"\b(?:other\s+than|excluding|except|does\s+not\s+include|not\s+including|"
    r"not\s+containing|without|no|not)\s+([a-z][a-z ,\-]{2,60})", re.I)


def _load_taxonomy() -> list[dict[str, Any]]:
    rows = list(csv.DictReader(open(_TAXONOMY_CSV, encoding="utf-8-sig")))
    out = []
    for r in rows:
        pattern = str(r.get("examples") or "").strip()
        if not pattern or str(r.get("criterion_type")) == "product_identity":
            continue  # identity는 정규식이 아니라 예시 목록 — 명사 폴백이 담당
        try:
            compiled = re.compile(pattern.replace(" | ", "|"), re.I)
        except re.error:
            continue
        out.append({"criterion_type": str(r["criterion_type"]),
                    "role": str(r.get("role") or ""), "pattern": compiled})
    return out


_TAXONOMY = _load_taxonomy()
_RESIDUAL_RX = next((t["pattern"] for t in _TAXONOMY if t["criterion_type"] == "residual_other"), None)


def CompileGroupDecisions(
    level: str,
    parent: str,
    members: dict[str, str],
) -> list[dict[str, Any]]:
    """Taxonomy-driven condition rows for one branch group (pure function).

    For each non-residual sibling label: run every taxonomy detector; each
    hit becomes one typed condition whose value is the matched span's
    content words, kept only if sibling-discriminative. exclusion_boundary
    captures the excluded phrase (whole-phrase block semantics downstream).
    residual_other labels emit nothing — else by elimination.
    """
    rows: list[dict[str, Any]] = []
    ordered = sorted(members.items())
    for seq, (code, label) in enumerate(ordered):
        clean = _COND_CLAUSE.sub(" ", str(label or ""))
        if _RESIDUAL_RX is not None and _RESIDUAL_RX.search(clean.lower()):
            continue  # else 분기
        siblings = tuple(l for c, l in ordered if c != code)
        sibling_toks = _toks(" ".join(siblings))
        # 형제 '배타' 필터는 상태×종 행렬 그룹(0203/0306: fresh·frozen 쌍이
        # 같은 종 라벨을 반복)에서 모든 토큰을 공유로 판정해 조건을 전멸시킨다
        # (실측: 0306 20형제 조건 0개). 판별력의 올바른 기준은 배타가 아니라
        # 희소성 — 형제 '과반'이 공유하는 토큰만 비판별로 기각한다.
        sib_tok_sets = [_toks(l) for l in siblings]
        half = max(1, len(sib_tok_sets)) / 2

        def _discriminative(w: str) -> bool:
            return sum(1 for s in sib_tok_sets if w in s) <= half

        def add(cond_type: str, op: str, values, source: str) -> None:
            rows.append({
                "level": level, "branch_id": parent, "seq": seq,
                "then_code": code, "cond_type": cond_type,
                "dto_field": CRITERION_FIELD_BINDING.get(cond_type, "*tokens*"),
                "op": op,
                "value": json.dumps(values, ensure_ascii=False) if values is not None else "null",
                "source_text": source[:120], "version": "parser-v1",
            })

        emitted_types: set[str] = set()
        # 배제 조건은 taxonomy 탐지기와 독립으로 캡처한다 — 단, dash(중간)
        # 계층의 부정("Uncooked pasta, NOT STUFFED or otherwise prepared")은
        # 구성품 상태라 광역 풀 배제로 쓰면 밀키트의 'prepared' 같은 요리
        # 수준 토큰에 정답이 위반당한다(실측). 그래서 부정 캡처는 leaf
        # 세그먼트(';' 뒤 마지막)에서만, dash 세그먼트는 긍정 조건만 낸다.
        leaf_segment = clean.rsplit(";", 1)[-1]
        for neg in _NEG_VALUE.finditer(leaf_segment):
            values = [w for w in _toks(neg.group(1)) if w][:4]
            if values:
                add("exclusion_boundary", "not_contains", sorted(values), neg.group(0))
                emitted_types.add("exclusion_boundary")
        positive_side = _NEG_VALUE.sub(" ", clean)
        for entry in _TAXONOMY:
            cond_type = entry["criterion_type"]
            if cond_type in ("residual_other", "exclusion_boundary"):
                continue
            match = entry["pattern"].search(positive_side)
            if not match:
                continue
            if cond_type == "quantitative_threshold":
                add(cond_type, "quant_gate", None, clean)
                emitted_types.add(cond_type)
                continue
            # has_token 유형: 값 추출 창은 패턴 스타일에 따라 다르다 —
            # 상태·종류형(frozen/swine/infants)은 매치 단어 자체가 값이고,
            # 연산어형(containing/consisting of/put up in)은 뒤따르는
            # 목적어가 값이다 (연산어를 값으로 쓰면 모든 라벨에 오발동).
            if cond_type in ("material_composition", "intended_use_function",
                             "packaging_presentation"):
                window = positive_side[match.end():match.end() + 40]
                span_source = window.split(";")[0].split(".")[0]
            else:
                span_source = match.group(0)
            # 값 상한 8: 법조문 열거("such as spaghetti, macaroni, noodles,
            # lasagne, gnocchi, ravioli, cannelloni")가 4에서 잘리면 정작
            # 판별력 있는 꼬리 단어(noodle)가 소실된다 — 1902 실측.
            # 배제(not_contains)는 차단 시맨틱이라 4 유지(보수).
            span_tokens = sorted(
                w for w in _toks(span_source) if _discriminative(w)
            )[:8]
            if span_tokens:
                add(cond_type, "has_token", span_tokens, match.group(0))
                emitted_types.add(cond_type)
        # 아무 유형도 안 잡힌 순수 명사 라벨 -> product_identity 폴백
        if not emitted_types:
            nouns = sorted(w for w in _toks(positive_side) if _discriminative(w))[:8]
            if nouns:
                add("product_identity", "has_token", nouns, clean)
    return rows


def _main() -> int:  # pragma: no cover — designer-run CLI
    args = sys.argv[1:]
    apply_mode = "--apply" in args
    chapters: tuple[str, ...] = ()
    if "--chapters" in args:
        chapters = tuple(
            c.strip().zfill(2) for c in args[args.index("--chapters") + 1].split(",") if c.strip()
        )

    from sqlalchemy import text

    from db.db_session_manager import DbSessionManager

    manager = DbSessionManager.GetInstance()
    chapter_label: dict[str, str] = {}
    try:
        for row in manager.FetchRows(text('SELECT chapter, title, description FROM "cn_chapter_index"'), {}):
            d = dict(row)
            ch = re.sub(r"\D", "", str(d.get("chapter") or ""))[:2].zfill(2)
            if ch:
                chapter_label[ch] = f"{d.get('title') or ''} {d.get('description') or ''}"[:200]
    except Exception:  # noqa: BLE001
        pass
    from agents.tools.cn_predicate_llm_compiler import EnrichSubheadingLabels

    rows = [dict(r) for r in manager.FetchRows(text(
        "SELECT cn8, coalesce(heading_description,'') AS h4,"
        " coalesce(subheading_description,'') AS h6,"
        " coalesce(cn8_description,'') AS h8,"
        " coalesce(combined_description,'') AS combined FROM cn_table"), {})]
    # --enrich-h6: dash 계층 포함 컴파일 (기본 OFF — 'not ... prepared' 배제가
    # 요리/구성품 상태 서열 미해결 상태에선 정답 면류를 위반시킬 위험 실측.
    # 극성·서열 처리와 함께 A/B로 도입한다.)
    if "--enrich-h6" in args:
        rows = EnrichSubheadingLabels(rows)
    if chapters:
        rows = [r for r in rows if str(r.get("cn8") or "")[:2] in set(chapters)]
    groups = _build_groups(rows, chapter_label)

    out: list[dict[str, Any]] = []
    per_level: dict[str, int] = {}
    branches_covered: dict[str, set] = {}
    for level, parent, _parent_label, members in groups:
        decision_rows = CompileGroupDecisions(level, parent, members)
        out.extend(decision_rows)
        per_level[level] = per_level.get(level, 0) + len(decision_rows)
        if decision_rows:
            branches_covered.setdefault(level, set()).add(parent)
    total_branches = {}
    for level, parent, _pl, _m in groups:
        total_branches[level] = total_branches.get(level, 0) + 1
    print(f"분기 그룹 {len(groups)}개 → 조건 행 {len(out)}개")
    for level in ("hs4", "hs6", "cn8"):
        covered = len(branches_covered.get(level, set()))
        print(f"  {level}: 조건 {per_level.get(level, 0)}개, 분기 커버 {covered}/{total_branches.get(level, 0)}")
    cond_types: dict[str, int] = {}
    for r in out:
        cond_types[r["cond_type"]] = cond_types.get(r["cond_type"], 0) + 1
    print(f"  조건 유형: {cond_types}")

    if apply_mode:
        with manager.OpenSession() as session:
            session.execute(text(
                'CREATE TABLE IF NOT EXISTS "branch_decision_index" ('
                "level text, branch_id text, seq int, then_code text,"
                "cond_type text, dto_field text, op text, value text,"
                "source_text text, version text)"))
            # 반복 재기록으로 테이블이 부풀면 일괄 DELETE가 statement
            # timeout에 걸린다(실측). 트랜잭션 한정 타임아웃 완화 + ctid
            # 청크 삭제로 문장 하나하나를 짧게 유지한다.
            session.execute(text("SET LOCAL statement_timeout = '300s'"))
            while True:
                deleted = session.execute(text(
                    'DELETE FROM "branch_decision_index" WHERE ctid IN ('
                    'SELECT ctid FROM "branch_decision_index"'
                    " WHERE version = :v LIMIT 2000)"), {"v": "parser-v1"})
                if (deleted.rowcount or 0) == 0:
                    break
            # 9,296행 개별 INSERT는 원거리 DB에서 순단에 취약(실측 1회 실패)
            # — executemany 일괄 전송으로 왕복을 청크당 1회로 줄인다.
            insert_sql = text(
                'INSERT INTO "branch_decision_index" VALUES ('
                ":level, :branch_id, :seq, :then_code, :cond_type,"
                " :dto_field, :op, :value, :source_text, :version)")
            for start in range(0, len(out), 1000):
                session.execute(insert_sql, out[start:start + 1000])
            session.commit()
        print(f"-> branch_decision_index에 {len(out)}행 기록")
    audit_dir = Path(__file__).resolve().parents[3] / "artifacts"
    audit_dir.mkdir(exist_ok=True)
    (audit_dir / "decision_table_audit.json").write_text(
        json.dumps({"groups": len(groups), "rows": len(out), "per_level": per_level,
                    "cond_types": cond_types}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
