"""CN IS-A alias compiler (offline, deterministic — no LLM).

The CN hierarchy itself is a species->class dictionary: 160555 "Octopus"
being a child of 1605 "Crustaceans, molluscs and other aquatic
invertebrates..." states that octopus IS-A mollusc. This compiler walks
cn_table lineage columns (heading/subheading/cn8 descriptions, plus the
chapter row from cn_chapter_index) and emits a global token->class map to
the sidecar table ``cn_alias_index``.

Consistency filter (no thresholds): a candidate token's alias set is the
INTERSECTION of its ancestor-class sets across every lineage it appears in.
Tokens living under many unrelated families (frozen, dried, other) end with
an empty intersection and are dropped; species/things (octopus, cockle,
buckwheat) survive with their stable class tokens.

Token normalisation intentionally mirrors staged_classification/_tokens so
the alias vocabulary joins the same match space.

Usage (designer runtime, DB env required):
  PYTHONPATH=src python -m agents.tools.cn_alias_compiler           # read-only audit
  PYTHONPATH=src python -m agents.tools.cn_alias_compiler --apply   # build sidecar
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_COND_CLAUSE = re.compile(r"whether\s+or\s+not[^,;.)]*", re.I)
_NEG_CLAUSE = re.compile(
    r"\b(?:not|no|other\s+than|excluding|without|except)\s+[a-z][a-z ,\-]{2,60}", re.I,
)
_TOKEN = re.compile(r"[a-z]+")

_FORM_WORDS = frozenset({
    "stuffed", "cooked", "uncooked", "frozen", "fresh", "chilled", "dried",
    "smoked", "salted", "boiled", "roasted", "steamed", "minced", "grated",
    "sweetened", "unsweetened", "sliced", "shelled", "concentrated", "live",
    "prepared", "preserved", "processed", "edible", "whole", "cut", "pieces",
})
_STOP = frozenset({
    "other", "than", "elsewhere", "specified", "included", "similar", "the",
    "and", "with", "for", "form", "forms", "that", "those", "not", "但",
    "containing", "content", "less", "more", "least", "most", "weight",
    "exceeding", "product", "products", "good", "goods", "preparation",
    "preparations", "food", "foods", "kind", "kinds", "use", "uses", "put",
    "sale", "retail", "heading", "headings", "subheading", "subheadings",
    "excluding", "except", "packing", "packings", "immediate", "net",
    # 법조문 보일러플레이트 — 'aid -> [chapter, note, thi]' 오염 실측 후 추가.
    # _STOP은 stem 기준 대조라 stem형(thi, note, chapter)으로 수록한다.
    "chapter", "note", "thi", "this", "having", "such", "which", "whether",
    "individual", "function", "purpose", "described", "referred",
})


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and not token.endswith(("ses", "oes")):
        return token[:-2] if token.endswith(("ches", "shes", "xes")) else token[:-1]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _class_tokens(label: str) -> frozenset[str]:
    cleaned = _NEG_CLAUSE.sub(" ", _COND_CLAUSE.sub(" ", str(label or "").lower()))
    return frozenset(
        _stem(t) for t in _TOKEN.findall(cleaned)
        if len(t) >= 3 and _stem(t) not in _STOP and t not in _FORM_WORDS
    )


def _child_tokens(label: str) -> frozenset[str]:
    return _class_tokens(label)  # same scrubbing; ambiguity dies in the intersection


def _main() -> int:  # pragma: no cover — designer-run CLI
    apply_mode = "--apply" in sys.argv
    from sqlalchemy import text

    from db.db_session_manager import DbSessionManager

    manager = DbSessionManager.GetInstance()

    chapter_label: dict[str, str] = {}
    try:
        for row in manager.FetchRows(
            text('SELECT chapter, title, description FROM "cn_chapter_index"'), {},
        ):
            data = dict(row)
            chapter = re.sub(r"\D", "", str(data.get("chapter") or ""))[:2].zfill(2)
            if chapter:
                chapter_label[chapter] = f"{data.get('title') or ''} {data.get('description') or ''}"
    except Exception:  # noqa: BLE001 — chapter tier is a bonus, not a requirement
        chapter_label = {}

    rows = manager.FetchRows(text(
        "SELECT cn8, coalesce(heading_description, '') AS h4,"
        " coalesce(subheading_description, '') AS h6,"
        " coalesce(cn8_description, '') AS h8 FROM cn_table"), {})

    # token -> list of ancestor-class frozensets (one per lineage occurrence)
    occurrences: dict[str, list[frozenset[str]]] = defaultdict(list)
    seen_lineage: set[tuple[str, str]] = set()
    for row in rows:
        d = dict(row)
        cn8 = str(d.get("cn8") or "")
        chapter = cn8[:2]
        tiers = [
            (str(d.get("h4") or ""), _class_tokens(chapter_label.get(chapter, ""))),
            (str(d.get("h6") or ""), _class_tokens(chapter_label.get(chapter, "")) | _class_tokens(d.get("h4"))),
            (str(d.get("h8") or ""), _class_tokens(d.get("h4")) | _class_tokens(d.get("h6"))),
        ]
        for label, ancestor_classes in tiers:
            if not label or not ancestor_classes:
                continue
            lineage_key = (label, ",".join(sorted(ancestor_classes))[:120])
            if lineage_key in seen_lineage:  # same label under same ancestry -> one vote
                continue
            seen_lineage.add(lineage_key)
            for token in _child_tokens(label):
                if token in ancestor_classes:
                    continue  # a class word is not an alias of itself
                occurrences[token].append(frozenset(ancestor_classes))

    aliases: dict[str, list[str]] = {}
    for token, class_sets in occurrences.items():
        merged = frozenset.intersection(*class_sets) if class_sets else frozenset()
        if merged:
            aliases[token] = sorted(merged)[:6]

    print(f"후보 토큰 {len(occurrences)}개 → 일관성 필터 생존 {len(aliases)}개")
    sample = sorted(aliases.items())[:12]
    for token, classes in sample:
        print(f"   {token} -> {classes}")
    for probe in ("octopu", "cockle", "salmon", "buckwheat", "frozen", "dried"):
        print(f"   probe {probe!r}: {aliases.get(probe, '(탈락/없음)')}")

    if apply_mode:
        with manager.OpenSession() as session:
            session.execute(text(
                'CREATE TABLE IF NOT EXISTS "cn_alias_index" ('
                "token text, class_tokens text, support int, alias_version text)"))
            session.execute(text('DELETE FROM "cn_alias_index" WHERE alias_version = :v'),
                            {"v": "tree-v1"})
            for token, classes in aliases.items():
                session.execute(
                    text('INSERT INTO "cn_alias_index" VALUES (:t, :c, :s, :v)'),
                    {"t": token, "c": json.dumps(classes, ensure_ascii=False),
                     "s": len(occurrences[token]), "v": "tree-v1"})
            session.commit()
        print(f"-> cn_alias_index에 {len(aliases)}개 기록")

    out_dir = Path(__file__).resolve().parents[3] / "artifacts"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "cn_alias_audit.json").write_text(
        json.dumps({"total_candidates": len(occurrences), "kept": len(aliases),
                    "sample": dict(sorted(aliases.items())[:200])}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"감사 리포트: {out_dir / 'cn_alias_audit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
