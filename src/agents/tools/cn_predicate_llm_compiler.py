"""LLM-translate + rule-verify predicate compiler (offline batch).

Reads branch GROUPS directly from cn_table (parent label + all sibling
labels — the branching question is only visible with the siblings side by
side), asks the LLM to TRANSLATE each label into structured predicates, and
accepts a predicate only if the mechanical verifier passes:

  V1  every value token exists in that sibling's own label (grounding —
      the LLM cannot invent vocabulary)
  V2  axis/op belong to the closed sets
  V3  no value token originates from a "whether or not ..." clause
      (irrelevance marker, not a condition)
  V4  form/processing values must be sibling-exclusive (a state every
      sibling shares cannot discriminate)

Trust lives in the verifier, not the model: a wrong translation fails V1-V4
and simply yields no predicate (lexical fallback continues to rank), never a
wrong hard-block. Rows are written to the SAME sidecar
``branch_predicate_index`` under predicate_version='llm-v1' so the runtime
can A/B against the rule pass via ASAP_PREDICATE_VERSION.

Usage (designer runtime, LLM + DB env required):
  PYTHONPATH=src python -m agents.tools.cn_predicate_llm_compiler --chapters 16,19 --limit 5
  PYTHONPATH=src python -m agents.tools.cn_predicate_llm_compiler --chapters 02,03,07,16,19,20,21 --apply
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from typing import Any

_TOKEN = re.compile(r"[a-z]+")
_COND_CLAUSE = re.compile(r"whether\s+or\s+not[^,;.)]*", re.I)
# llm-v1 축(식품 파일럿에서 쓴 임시 6축) — 측정 자산이라 유지
_AXES_V1 = frozenset({"species", "contains", "form", "processing", "negation", "pct"})
# llm-v2 축 = taxonomy CSV의 criterion_type 전체(전품목 술어 분류 기준).
# residual_other는 소거(else)라 술어를 내지 않는다.
_TAXONOMY_CSV_PATH = None  # 지연 로드
def _taxonomy_rows():
    import csv
    from pathlib import Path as _P
    path = _P(__file__).resolve().parents[3] / "data" / "classification_criterion_taxonomy_20260702.csv"
    return [r for r in csv.DictReader(open(path, encoding="utf-8-sig"))
            if str(r.get("criterion_type")) != "residual_other"]
_AXES_V2 = frozenset(r["criterion_type"] for r in _taxonomy_rows())
_AXES = _AXES_V1 | _AXES_V2  # 검증기 폐쇄집합은 두 세대 합집합
_OPS = frozenset({"has_token", "not_contains", "quant_gate"})

AXIS_FIELD_BINDING = {
    "species": (
        "identity_hints.normalized_tariff_description;identity_hints.identity_terms;"
        "identity_hints.ingredient_class;composition_facts.ingredient_classes;"
        "composition_facts.principal_ingredient"
    ),
    "form": (
        "identity_hints.food_form;identity_hints.product_form_terms;"
        "composition_facts.contains_wrapper_or_dough;composition_facts.contains_sauce_or_broth"
    ),
    "processing": "identity_hints.processing_state;composition_facts.processing_state",
    "contains": (
        "identity_hints.normalized_tariff_description;identity_hints.identity_terms;"
        "composition_facts.ingredient_classes;composition_facts.principal_ingredient;"
        "composition_facts.composition_terms"
    ),
    "negation": "*tokens*",
    "pct": "composition_facts.ingredient_percentages",
}

_SYSTEM_PROMPT = """You translate EU Combined Nomenclature branch labels into structured
classification predicates. You are a PARSER, not an author: every value word
must be copied from the sibling's own label text. Output one JSON object only.

For each sibling label, emit zero or more predicates:
  axis: species | contains | form | processing | negation | pct
  op:   has_token (label asserts the product IS/HAS this)
        not_contains (label EXCLUDES products having this)
        quant_gate (a % / weight threshold decides — no value needed)
  value: 1-4 lowercase words copied from THAT label

Rules:
- "whether or not X" clauses are irrelevance markers: never emit predicates
  from their words.
- A state word every sibling shares does not discriminate: skip it.
- "Other ..." residual lines define themselves by elimination: emit nothing.
- When a label is a plain noun (a species/thing), emit ONE species predicate
  with its distinctive noun(s).
Return: {"predicates": [{"code": "<sibling code>", "axis": "...", "op": "...",
"value": ["..."], "confidence": 0.0-1.0}, ...]}"""


def _build_v2_prompt() -> str:
    lines = []
    for r in _taxonomy_rows():
        ct = r["criterion_type"]
        op = ("not_contains" if ct == "exclusion_boundary"
              else "quant_gate" if ct == "quantitative_threshold" else "has_token")
        lines.append(f"  {ct} (op={op}): {str(r.get('definition') or '')[:90]}")
    axis_block = "\n".join(lines)
    return f"""You translate EU Combined Nomenclature branch labels into structured
classification predicates for ANY product domain. You are a PARSER, not an
author: every value word must be copied from the sibling's own label text.
Output one JSON object only.

For each sibling label, emit zero or more predicates. axis MUST be one of the
criterion types below (taxonomy of classification criteria):
{axis_block}

  op: has_token (label asserts the product IS/HAS this)
      not_contains (label EXCLUDES products having this)
      quant_gate (a %/weight/size threshold decides — no value needed)
  value: 1-4 lowercase words copied from THAT label

Rules:
- "whether or not X" clauses are irrelevance markers: never emit predicates
  from their words.
- A state word every sibling shares does not discriminate: skip it.
- "Other ..." residual lines define themselves by elimination: emit nothing.
- When a label is a plain noun (a species/thing/article), emit ONE
  product_identity or species_source predicate with its distinctive noun(s).
Return: {{"predicates": [{{"code": "<sibling code>", "axis": "...", "op": "...",
"value": ["..."], "confidence": 0.0-1.0}}, ...]}}"""


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and not token.endswith(("ses", "oes")):
        return token[:-2] if token.endswith(("ches", "shes", "xes")) else token[:-1]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _toks(text: str) -> set[str]:
    return {_stem(t) for t in _TOKEN.findall(str(text or "").lower()) if len(t) >= 3}


def VerifyPredicate(
    pred: dict[str, Any],
    label: str,
    sibling_labels: tuple[str, ...],
) -> str:
    """'' if the predicate passes V1-V4, else the failed rule name."""
    axis = str(pred.get("axis") or "")
    op = str(pred.get("op") or "")
    if axis not in _AXES or op not in _OPS:
        return "V2_closed_sets"
    if op == "quant_gate":
        return ""
    values = [str(v).strip().lower() for v in (pred.get("value") or []) if str(v).strip()]
    if not values or len(values) > 4:
        return "V2_value_arity"
    label_tokens = _toks(label)
    cond_tokens = set()
    for m in _COND_CLAUSE.finditer(str(label or "")):
        cond_tokens |= _toks(m.group(0))
    sibling_tokens = _toks(" ".join(sibling_labels))
    for value in values:
        vtoks = _toks(value)
        if not vtoks or not vtoks <= label_tokens:
            return "V1_grounding"
        if vtoks & cond_tokens:
            return "V3_conditional_clause"
        if axis in ("form", "processing", "physical_form", "preservation_state",
                    "processing_method", "condition_quality") and op == "has_token" and vtoks & sibling_tokens:
            return "V4_sibling_shared"
    return ""


def EnrichSubheadingLabels(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """h6 라벨을 combined_description의 중간(dash) 계층 포함으로 교체.

    cn_table.subheading_description은 leaf 문구만 담아서 190219의 라벨이
    'Other'가 된다 — 정작 분기를 정의하는 "Uncooked pasta, not stuffed or
    otherwise prepared"는 combined 경로에 살아있는데 안 읽히고 있었다
    (실측: 1902 hs6 그룹에 uncooked/stuffed 조건 부재 → 짬뽕 0:0).
    경로 세그먼트 [2:-1](heading 다음 ~ leaf 이전) + leaf를 합쳐 h6 원문으로
    쓴다. combined가 없거나 짧으면 기존 h6 유지 (무손실 폴백).
    """
    for r in rows:
        combined = str(r.get("combined") or "")
        if ">" not in combined:
            continue
        segments = [s.strip() for s in combined.split(">")]
        middle = [s for s in segments[2:-1] if s]
        if middle:
            # ';' 구분자: 부정 캡처 창([a-z ,\-]{2,60})이 세그먼트 경계를
            # 넘지 못하게 차단 — 무구분 병합은 "not stuffed ... Containing
            # eggs"를 한 부정으로 삼켜 190211을 '계란 배제'로 반전시켰다(실측).
            r["h6"] = " ; ".join([*middle, str(r.get("h6") or "")]).strip()
    return rows


def _build_groups(rows: list[dict[str, Any]], chapter_label: dict[str, str]):
    """(level, parent_code, parent_label, {code: label}) branch groups."""
    h4: dict[str, dict[str, str]] = defaultdict(dict)
    h6: dict[str, dict[str, str]] = defaultdict(dict)
    h8: dict[str, dict[str, str]] = defaultdict(dict)
    h4_label: dict[str, str] = {}
    h6_label: dict[str, str] = {}
    for r in rows:
        cn8 = str(r.get("cn8") or "")
        if len(cn8) != 8:
            continue
        l4, l6, l8 = str(r.get("h4") or ""), str(r.get("h6") or ""), str(r.get("h8") or "")
        h4[cn8[:2]][cn8[:4]] = l4
        h4_label[cn8[:4]] = l4
        if l6:
            h6[cn8[:4]][cn8[:6]] = l6
            h6_label[cn8[:6]] = l6
        if l8:
            h8[cn8[:6]][cn8] = l8
    out = []
    for parent, members in h4.items():
        if len(members) > 1:
            out.append(("hs4", parent, chapter_label.get(parent, ""), members))
    for parent, members in h6.items():
        if len(members) > 1:
            out.append(("hs6", parent, h4_label.get(parent, ""), members))
    for parent, members in h8.items():
        if len(members) > 1:
            out.append(("cn8", parent, h6_label.get(parent, "") or h4_label.get(parent[:4], ""), members))
    return out


def _main() -> int:  # pragma: no cover — designer-run CLI
    args = sys.argv[1:]
    apply_mode = "--apply" in args
    chapters = ("02", "03", "07", "16", "19", "20", "21")
    if "--chapters" in args:
        spec = args[args.index("--chapters") + 1]
        # 'all' = 전 챕터(01~99) — 필터 없이 cn_table 전량. 비식품 테스트셋
        # (US_KR 등) 확장용. 그룹 수 = LLM 콜 수이므로 먼저 --limit 없이
        # 드라이런으로 콜 수를 확인하고 --apply 하라.
        chapters = () if spec.strip().lower() == "all" else tuple(
            c.strip().zfill(2) for c in spec.split(",") if c.strip()
        )
    limit = 0
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    # --taxonomy: llm-v2 세대 — 축=taxonomy 16유형, dto_field=결정 컴파일러의
    # CRITERION_FIELD_BINDING, predicate_version='llm-v2'. 전품목 확장용.
    tax_mode = "--taxonomy" in args

    from sqlalchemy import text

    from agents.candiate_classfier import build_runtime_adapter
    from bussiness_logic.bridge.schema import LlmGenerationOptions, LlmRequest
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

    rows = [dict(r) for r in manager.FetchRows(text(
        "SELECT cn8, coalesce(heading_description,'') AS h4,"
        " coalesce(subheading_description,'') AS h6,"
        " coalesce(cn8_description,'') AS h8,"
        " coalesce(combined_description,'') AS combined FROM cn_table"), {})]
    if "--enrich-h6" in args:
        rows = EnrichSubheadingLabels(rows)
    if chapters:
        rows = [r for r in rows if str(r.get("cn8") or "")[:2] in set(chapters)]
    groups = _build_groups(rows, chapter_label)
    if limit:
        groups = groups[:limit]
    print(f"챕터 {','.join(chapters) if chapters else '전체(01~99)'}: 분기 그룹 {len(groups)}개 (LLM 콜 수와 동일)")

    adapter = build_runtime_adapter()
    accepted: list[dict[str, Any]] = []
    stats = {"groups": 0, "raw": 0, "accepted": 0}
    reject = defaultdict(int)
    for level, parent, parent_label, members in groups:
        stats["groups"] += 1
        member_view = [{"code": c, "label": l[:200]} for c, l in sorted(members.items())]
        prompt = (
            f"Branch parent ({level} group under {parent}):\n{parent_label[:200]}\n"
            f"Sibling lines:\n{json.dumps(member_view, ensure_ascii=False)}"
        )
        system_prompt = _build_v2_prompt() if tax_mode else _SYSTEM_PROMPT
        try:
            resp = adapter.Generate(LlmRequest(
                user_prompt=prompt, system_prompt=system_prompt,
                generation_options=LlmGenerationOptions(temperature=0, max_tokens=1400),
            ))
            raw = str(getattr(resp, "generatedText", ""))
            start, end = raw.find("{"), raw.rfind("}")
            parsed = json.loads(raw[start:end + 1]) if 0 <= start < end else {}
        except Exception as error:  # noqa: BLE001 — skip group, lexical fallback covers it
            reject[f"llm_error:{type(error).__name__}"] += 1
            continue
        for pred in parsed.get("predicates") or []:
            stats["raw"] += 1
            code = re.sub(r"\D", "", str(pred.get("code") or ""))
            if code not in members:
                reject["V0_unknown_code"] += 1
                continue
            label = members[code]
            fail = VerifyPredicate(pred, label, tuple(l for c, l in members.items() if c != code))
            if fail:
                reject[fail] += 1
                continue
            axis = str(pred["axis"])
            if tax_mode and axis not in _AXES_V2:
                reject["V2_axis_not_taxonomy"] += 1
                continue
            if not tax_mode and axis not in _AXES_V1:
                reject["V2_axis_not_v1"] += 1
                continue
            if tax_mode:
                from agents.tools.branch_decision_compiler import CRITERION_FIELD_BINDING
                field_binding = CRITERION_FIELD_BINDING.get(axis, "*tokens*")
            else:
                field_binding = AXIS_FIELD_BINDING.get(axis, "*tokens*")
            accepted.append({
                "level": level, "parent_code": parent, "code": code,
                "predicate_id": f"llm-{level}-{code}-{stats['accepted']}",
                "axis": axis, "dto_field": field_binding,
                "op": str(pred["op"]),
                "value": json.dumps([str(v).lower() for v in (pred.get("value") or [])],
                                    ensure_ascii=False),
                "unit": "", "severity": "hard_block" if pred["op"] == "not_contains" else (
                    "delegated" if pred["op"] == "quant_gate" else "boost"),
                "source": "llm",
                "confidence": float(pred.get("confidence") or 0.5),
                "compile_status": "active",
                "source_text": label[:120],
                "predicate_version": "llm-v2" if tax_mode else "llm-v1",
            })
            stats["accepted"] += 1
        if stats["groups"] % 20 == 0:
            print(f"  ...{stats['groups']}/{len(groups)} 그룹, 채택 {stats['accepted']}")
    print(f"그룹 {stats['groups']} | LLM 술어 {stats['raw']} | 검증 통과 {stats['accepted']}")
    print(f"기각 사유: {dict(reject)}")

    if apply_mode and accepted:
        with manager.OpenSession() as session:
            session.execute(text('DELETE FROM "branch_predicate_index" WHERE predicate_version = :v'),
                            {"v": "llm-v2" if tax_mode else "llm-v1"})
            for item in accepted:
                session.execute(text(
                    'INSERT INTO "branch_predicate_index" VALUES ('
                    ":level, :parent_code, :code, :predicate_id, :axis, :dto_field,"
                    " :op, :value, :unit, :severity, :source, :confidence,"
                    " :compile_status, :source_text, :predicate_version)"), item)
            session.commit()
        print(f"-> {'llm-v2' if tax_mode else 'llm-v1'}으로 {len(accepted)}개 기록")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
