"""Branch predicate compiler (offline, rule pass — no LLM).

Compiles each branch_index row's label/condition columns into structured
decision predicates, written to a SIDECAR table ``branch_predicate_index``
(the original hs4/hs6/cn8_branch_index tables are not touched, so the whole
layer can be A/B-tested or dropped without risk).

Rule pass only extracts what is deterministically derivable:
  pct       : quantitative/hard conditions exist -> delegated to the runtime
              quant gate (no re-parse here; marker for coverage/audit)
  negation  : label negation clauses (not/no/without/excluding/other than/
              except) -> product holding that token violates the branch.
              "whether or not X" clauses are scrubbed FIRST — they are
              irrelevance markers, not conditions.
  contains  : "containing X" (positive context) -> product holding X supports
  species   : Latin binomial in parentheses -> species evidence
  form      : CN form/processing participles (stuffed/frozen/minced/...)
              excluding chapter-generic prepared/preserved
  residual  : residual_other_flag marker — evaluated by ELIMINATION at
              runtime (complement of siblings), never as its own condition

Audit fields per predicate row: source/confidence/compile_status/source_text
so an LLM/manual pass can extend the same table under review flags.

Usage (designer runtime, DB env required):
  PYTHONPATH=src python -m agents.tools.branch_predicate_compiler           # read-only coverage audit
  PYTHONPATH=src python -m agents.tools.branch_predicate_compiler --apply   # create/refresh sidecar
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_TABLES = {"hs4": "hs4_branch_index", "hs6": "hs6_branch_index", "cn8": "cn8_branch_index"}

_COND_CLAUSE = re.compile(r"whether\s+or\s+not[^,;.)]*", re.I)
_NEG_CLAUSE = re.compile(
    r"\b(?:not|no|other\s+than|excluding|without|except)\s+([a-z][a-z ,\-]{2,60})", re.I,
)
_CONTAINS = re.compile(r"\bcontaining\s+(?!no\b)([a-z][a-z \-]{2,40})", re.I)
_LATIN = re.compile(r"\(([A-Z][a-z]{2,}\s+[a-z]{3,})")
_TOKEN = re.compile(r"[a-z]+")

# CN form/processing participles that answer a physical-state question.
# prepared/preserved are chapter-generic and excluded on purpose.
_FORM_LEXICON = frozenset({
    "stuffed", "cooked", "uncooked", "frozen", "fresh", "chilled", "dried",
    "smoked", "salted", "boiled", "roasted", "steamed", "minced", "grated",
    "sweetened", "unsweetened", "sliced", "shelled", "concentrated",
})
_STOP = frozenset({
    "other", "than", "elsewhere", "specified", "included", "similar",
    "the", "and", "with", "for", "form", "forms", "that", "those",
    "subheading", "subheadings", "heading", "headings",
    # grammar words measured leaking into negation values ("not CONTAINING
    # cocoa or containing LESS than 40%...") and hard-blocking on stray
    # product tokens: these describe the CONDITION, never the product.
    "containing", "content", "less", "more", "least", "most", "weight",
    "exceeding", "product", "products", "good", "goods", "preparation",
    "preparations", "food", "foods", "powder", "material", "materials",
    "kind", "kinds", "use", "uses", "put", "sale", "retail",
})
# "not containing X or containing less/more than N %" is a compound
# QUANTITATIVE condition — the quant gate owns it, not a token negation.
_QUANT_NEG = re.compile(r"(?:not\s+)?containing[^,;.)]{0,60}?\b(?:less|more)\s+than\s+\d", re.I)


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and not token.endswith(("ses", "oes")):
        return token[:-2] if token.endswith(("ches", "shes", "xes")) else token[:-1]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text: str) -> list[str]:
    return sorted({
        _stem(t) for t in _TOKEN.findall(str(text or "").lower())
        if len(t) >= 3 and _stem(t) not in _STOP
    })


# axis -> DTO fields the question reads (graded eval falls back to the
# whole token pool at reduced weight, so free-ish typed values cannot
# starve a branch into all-unknown).
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
    "negation": "*tokens*",  # violation detection needs recall over precision
}


def CompileRow(
    row: dict[str, Any],
    sibling_labels: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Deterministic predicates for one branch row.

    ``sibling_labels``: labels of the OTHER rows in the same parent group.
    A form participle is only a question if it discriminates — a token the
    siblings also carry (or that appears in an or-enumeration of allowed
    states, e.g. "fresh, chilled or frozen") is scope wording, not a
    condition (measured: 0306's state list boosted it for every product).
    """
    label = str(row.get("option_label_en") or "")
    scrubbed = _COND_CLAUSE.sub(" ", label)  # irrelevance clauses first
    scrubbed = _QUANT_NEG.sub(" ", scrubbed)  # compound %-conditions -> quant gate
    preds: list[dict[str, Any]] = []

    def add(axis: str, op: str, value: Any, severity: str, source_text: str) -> None:
        preds.append({
            "axis": axis,
            "dto_field": AXIS_FIELD_BINDING.get(axis, "*tokens*"),
            "op": op,
            "value": value,
            "severity": severity,
            "source": "rule",
            "confidence": 1.0,
            "compile_status": "active",
            "source_text": source_text[:120],
        })

    if str(row.get("residual_other_flag") or "").strip().lower() == "true":
        preds.append({
            "axis": "residual", "dto_field": "", "op": "complement", "value": None,
            "severity": "structural", "source": "rule", "confidence": 1.0,
            "compile_status": "active", "source_text": label[:120],
        })
    if str(row.get("quantitative_conditions") or "").strip() or str(row.get("hard_conditions") or "").strip():
        preds.append({
            "axis": "pct", "dto_field": "composition_facts.ingredient_percentages",
            "op": "quant_gate", "value": None, "severity": "delegated",
            "source": "rule", "confidence": 1.0, "compile_status": "active",
            "source_text": str(row.get("quantitative_conditions") or row.get("hard_conditions"))[:120],
        })
    for match in _NEG_CLAUSE.finditer(scrubbed):
        values = _tokens(match.group(1))[:4]
        if values:
            add("negation", "not_contains", values, "hard_block", match.group(0))
    positive_side = _NEG_CLAUSE.sub(" ", scrubbed)
    for match in _CONTAINS.finditer(positive_side):
        values = _tokens(match.group(1))[:4]
        if values:
            add("contains", "has_token", values, "boost", match.group(0))
    for match in _LATIN.finditer(label):
        values = _tokens(match.group(1))[:3]
        if values:
            add("species", "has_token", values, "boost", match.group(0))
    # Noun-phrase species: the label's own ingredient/thing nouns that the
    # SIBLINGS do not share and that are not form/state words. These match
    # lexical positive_terms too, but bound to the species DTO scope + IS-A
    # alias expansion they become a class judgement lexical cannot make
    # (octopus ∈ molluscs). Discriminative-only, so no double-count noise.
    sibling_text = " ".join(sibling_labels).lower()
    sibling_toks = set(_tokens(sibling_text))
    if not any(p["axis"] == "species" for p in preds):
        head = _NEG_CLAUSE.sub(" ", scrubbed)
        nouns = [
            tok for tok in _tokens(head)
            if tok not in sibling_toks
            and tok not in _FORM_LEXICON
            and _stem(tok) not in _FORM_LEXICON
        ]
        if nouns and len(nouns) <= 4:
            add("species", "has_token", nouns[:4], "boost",
                "noun-phrase: " + ",".join(nouns[:4]))
    form_hits = sorted(set(_TOKEN.findall(positive_side.lower())) & _FORM_LEXICON)
    if form_hits:
        # (1) An or-enumeration of states ("fresh, chilled or frozen") is an
        #     allowance, not a question — skip when several states co-occur.
        # (2) A state the siblings also mention cannot discriminate them —
        #     compile-time sibling-IDF.
        sibling_text = " ".join(sibling_labels).lower()
        discriminative = [
            t for t in form_hits
            if t not in sibling_text
        ]
        if len(form_hits) <= 2 and discriminative:
            add("form", "has_token", [_stem(t) for t in discriminative][:4], "boost",
                "form participles: " + ",".join(discriminative))
    return preds


def _main() -> int:  # pragma: no cover — designer-run CLI
    apply_mode = "--apply" in sys.argv
    from sqlalchemy import text

    from db.db_session_manager import DbSessionManager

    manager = DbSessionManager.GetInstance()
    audit: dict[str, Any] = {}
    if apply_mode:
        with manager.OpenSession() as session:
            session.execute(text(
                'CREATE TABLE IF NOT EXISTS "branch_predicate_index" ('
                "level text, parent_code text, code text, predicate_id text,"
                "axis text, dto_field text, op text, value text, unit text,"
                "severity text, source text, confidence real,"
                "compile_status text, source_text text, predicate_version text)"
            ))
            session.execute(text(
                'DELETE FROM "branch_predicate_index" WHERE predicate_version IN (:v1, :v2)'),
                {"v1": "rule-v1", "v2": "rule-v2"})
            session.commit()
    for level, table in _TABLES.items():
        rows = manager.FetchRows(text(
            f'SELECT code, parent_code, option_label_en, quantitative_conditions,'
            f' hard_conditions, residual_other_flag FROM "{table}"'), {})
        total, tagged, axis_count = 0, 0, {}
        inserts: list[dict[str, Any]] = []
        by_parent: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            d = dict(r)
            by_parent.setdefault(str(d.get("parent_code") or ""), []).append(d)
        for r in rows:
            d = dict(r)
            total += 1
            siblings = tuple(
                str(s.get("option_label_en") or "")
                for s in by_parent.get(str(d.get("parent_code") or ""), [])
                if str(s.get("code")) != str(d.get("code"))
            )
            preds = CompileRow(d, sibling_labels=siblings)
            real = [p for p in preds if p["axis"] not in ("residual",)]
            if real:
                tagged += 1
            for i, p in enumerate(preds):
                axis_count[p["axis"]] = axis_count.get(p["axis"], 0) + 1
                inserts.append({
                    "level": level, "parent_code": str(d.get("parent_code") or ""),
                    "code": str(d.get("code") or ""),
                    "predicate_id": f"{level}-{d.get('code')}-{i}",
                    "axis": p["axis"], "dto_field": p["dto_field"], "op": p["op"],
                    "value": json.dumps(p["value"], ensure_ascii=False),
                    "unit": "", "severity": p["severity"], "source": p["source"],
                    "confidence": p["confidence"], "compile_status": p["compile_status"],
                    "source_text": p["source_text"], "predicate_version": "rule-v2",
                })
        audit[level] = {"rows": total, "tagged": tagged,
                        "coverage_pct": round(tagged / total * 100, 1) if total else 0,
                        "axis_count": axis_count}
        print(f"== {table}: {total}행 중 술어 태깅 {tagged}행 ({audit[level]['coverage_pct']}%)  축: {axis_count}")
        if apply_mode and inserts:
            with manager.OpenSession() as session:
                for chunk_start in range(0, len(inserts), 500):
                    for item in inserts[chunk_start:chunk_start + 500]:
                        session.execute(text(
                            'INSERT INTO "branch_predicate_index" VALUES ('
                            ":level, :parent_code, :code, :predicate_id, :axis,"
                            " :dto_field, :op, :value, :unit, :severity, :source,"
                            " :confidence, :compile_status, :source_text, :predicate_version)"),
                            item)
                    session.commit()
            print(f"   -> sidecar에 {len(inserts)}개 술어 기록")
    out_dir = Path(__file__).resolve().parents[3] / "artifacts"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "predicate_compile_coverage.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n감사 리포트: {out_dir / 'predicate_compile_coverage.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
