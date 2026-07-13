"""LLM agent for ProductUnderstanding identity lane.

Baseline-styled, additive path:
  - product name + Wikipedia-derived identity evidence
  - JSON-completion with chapter-index context

The agent never emits HS/CN codes or direct routing decisions; it only enriches
current identity fields and routing hint terms.
"""

from __future__ import annotations

import json
import os
import re

from agents.pipeline_dto import DistilledIdentityFacts, EncyclopediaEvidenceSet


DOMAIN_HINT_VOCAB = (
    "food",
    "cosmetics",
    "pharmaceutical",
    "hazardous",
    "animal_origin",
    "other",
)

_IDENTITY_SYSTEM_PROMPT = f"""
Return only one JSON object. No markdown, no code fence.
You are IdentityHintAgent. Convert product name + Wikipedia-derived identity
evidence into HS2 routing hint terms. Do NOT output HS/CN/TARIC codes,
documents, ingredient percentages, or composition facts.

Rules:
- Use only the supplied evidence. The product name itself IS evidence: when
  encyclopedia evidence is empty, still translate the name and fill what the
  name alone supports (never return an empty object).
- Do not invent ingredients or forms.
- Use Wikipedia processing/form signal terms only as identity-routing evidence.
- Keep translated/common-English wording short and stable.
- Translate the product into tariff-style English wording where possible.
- domain_hints values MUST be subset of: {", ".join(DOMAIN_HINT_VOCAB)}.

Use the provided cn_chapter_index descriptions/keywords to propose up to 8
chapter_hint_terms. Each term should be a short English or Korean keyword phrase.
product_form_terms may include physical form and preparation/processing signal
terms when they are present in the Wikipedia evidence.

Pipeline role (ontology summary):
- ProductUnderstandingFacts feeds DomainRouter, not final classification.
- DomainRouter matches chapter_hint_terms/product_form_terms/processing_state
  against cn_chapter_index include/exclude/guardrail columns.
- Prepared foods must not route only by raw ingredient/allergen mentions.
- Never output HS/CN/TARIC codes; code selection happens downstream.

ingredient_class / food_form / processing_state: short lowercase English
word(s) naming the principal ingredient family, the physical/commercial form,
and the processing state — ONLY when the supplied evidence supports them;
otherwise an empty string. Use tariff-register wording found in the chapter
context, not marketing language.

principal_ingredient_guess / accessory_ingredients: FACTUAL report of the
ingredient ORDER, not a legal judgement — principal = the single ingredient
most likely listed FIRST on the label (highest content); accessories = minor
components (sauces, broth, seasonings, garnish). Lowercase English. Empty
when the evidence does not say. Do NOT decide what the product "essentially
is" — report ingredient ranking only.

JSON keys (all required):
translated_product_name, commercial_identity, normalized_tariff_description,
identity_terms, product_form_terms, domain_hints,
ingredient_class, food_form, processing_state,
principal_ingredient_guess, accessory_ingredients,
chapter_hint_terms, chapter_hint_source_terms, chapter_hint_basis,
chapter_hint_status, confidence, needs_review.
""".strip()

_adapter_cache: list[object] = []
_chapter_context_cache: list[str] = []
_chapter_vocab_cache: list[frozenset[str]] = []


def _chapter_vocab() -> frozenset[str]:
    """Word vocabulary of the cn_chapter_index context (DB text, cached).

    Typed identity fields are accepted only when grounded in this vocabulary —
    the same DB-grounding idea as chapter_hint_terms, with no enum in the
    prompt and no hand-written word list.
    """
    if not _chapter_vocab_cache:
        _chapter_vocab_cache.append(
            frozenset(re.findall(r"[a-z]{3,}", _chapter_context().lower())),
        )
    return _chapter_vocab_cache[0]


def _grounded_typed_field(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text or len(text) > 40:
        return ""
    tokens = re.findall(r"[a-z]+", text)
    if tokens and any(token in _chapter_vocab() for token in tokens):
        return text
    return ""


def _get_adapter() -> object:
    if not _adapter_cache:
        from agents.runtime_adapter import BuildPipelineRuntimeAdapter

        _adapter_cache.append(BuildPipelineRuntimeAdapter())
    return _adapter_cache[0]


def _extract_json(text: str) -> dict[str, object]:
    raw = str(text or "").strip()
    if "```" in raw:
        raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        try:
            value = json.loads(raw[start : end + 1])
            if isinstance(value, dict):
                return value
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _chapter_context() -> str:
    """Compact chapter-index context used only for hint grounding."""
    if _chapter_context_cache:
        return _chapter_context_cache[0]

    lines: list[str] = []
    try:
        from agents.tools.chapter_index_repository import LoadPreClassificationChapterRows

        for row in LoadPreClassificationChapterRows():
            chapter = str(row.get("chapter") or "").strip()
            parts = [
                str(row.get("title") or "").strip(),
                str(row.get("description") or "").strip(),
                str(row.get("heading_scope") or "").strip(),
                str(row.get("chapter_keywords") or "").strip(),
                str(row.get("raw_scope_signals") or "").strip(),
                str(row.get("prepared_scope_signals") or "").strip(),
            ]
            if chapter and any(parts):
                scope = " | ".join(part for part in parts if part)
                lines.append(f"{chapter}: {scope}".rstrip())
    except Exception:  # noqa: BLE001 — best-effort context build
        lines = []

    context = "cn_chapter_index (chapter: scope):\n" + "\n".join(lines[:97]) if lines else ""
    _chapter_context_cache.append(context)
    return context


def _compact_evidence(
    *,
    productName: str,
    distilledIdentity: DistilledIdentityFacts,
    encyclopediaEvidence: EncyclopediaEvidenceSet,
    factTexts: tuple[str, ...] = (),
) -> str:
    encyc = "\n".join(
        f"- {entry.title}: {entry.description[:220]}"
        for entry in encyclopediaEvidence.entries[:3]
    )
    # ASAP_IDENTITY_FACTS=1: 라벨 사실 텍스트(원재료명 등)를 identity 번역
    # 문맥에 포함 — DTO를 채우는 LLM이 이름+위키만 보던 정보 절단의 처방.
    # 기본 OFF(기존 기준선 보존). 크롤 노이즈 유입 방지로 상한 8줄/720자.
    label_block = ""
    if (os.environ.get("ASAP_IDENTITY_FACTS", "0") or "0").strip() == "1" and factTexts:
        lines = [str(x).strip()[:180] for x in factTexts if str(x).strip()][:8]
        label_block = "\n\nproduct_label_facts:\n" + "\n".join(f"- {x}" for x in lines)[:720]
    return (
        f"product_name: {productName}\n"
        f"distilled_commercial_identity: {distilledIdentity.commercialIdentity}\n"
        f"distilled_description: {distilledIdentity.normalizedDescription}\n"
        f"identity_terms: {', '.join(distilledIdentity.identityTerms)}\n"
        f"product_form_signal_terms: {', '.join(distilledIdentity.productFormSignalTerms)}\n"
        f"processing_signal_terms: {', '.join(distilledIdentity.processingSignalTerms)}\n\n"
        f"encyclopedia_evidence:\n{encyc or '-'}"
        f"{label_block}"
    )


def _dedup_strings(
    values: object,
    *,
    limit: int,
    allow_single_char: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, tuple):
        rawValues = values
    elif isinstance(values, list):
        rawValues = tuple(values)
    else:
        rawValues = (str(values).strip(),) if str(values).strip() else ()

    out: list[str] = []
    for item in rawValues:
        text = str(item or "").strip()
        if not text:
            continue
        if not allow_single_char and len(text) < 2:
            continue
        if text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return tuple(out)


class IdentityHintAgent:
    """Build bounded HS2 routing hints from product and encyclopedia evidence."""

    def BuildIdentityFacts(
        self,
        *,
        productName: str,
        distilledIdentity: DistilledIdentityFacts,
        encyclopediaEvidence: EncyclopediaEvidenceSet,
        max_tokens: int | None = None,
        factTexts: tuple[str, ...] = (),
    ) -> dict[str, object]:
        return _BuildIdentityFacts(
            productName=productName,
            distilledIdentity=distilledIdentity,
            encyclopediaEvidence=encyclopediaEvidence,
            max_tokens=max_tokens,
            factTexts=factTexts,
        )


def _BuildIdentityFacts(
    *,
    productName: str,
    distilledIdentity: DistilledIdentityFacts,
    encyclopediaEvidence: EncyclopediaEvidenceSet,
    max_tokens: int | None = None,
    factTexts: tuple[str, ...] = (),
) -> dict[str, object]:
    """Combine evidence into identity fields via one LLM call.

    Returns a dict keyed by ``IdentityHintSet`` fields plus
    understanding mode + error fields. On failure returns a best-effort failure
    payload; caller overlays regex identity.
    """
    from bussiness_logic.bridge.schema import LlmGenerationOptions, LlmRequest

    tokens = max_tokens if max_tokens is not None else int(
        os.environ.get("ASAP_PRODUCT_UNDERSTANDING_MAX_TOKENS", "4096")
    )
    user_prompt = _compact_evidence(
        productName=productName,
        distilledIdentity=distilledIdentity,
        encyclopediaEvidence=encyclopediaEvidence,
        factTexts=factTexts,
    )
    chapter_context = _chapter_context()
    if chapter_context:
        user_prompt = f"{user_prompt}\n\n{chapter_context}"
    # 빈/무효 응답은 1회 재시도 — US_KR name-only 실측에서 실패 10건 중
    # 8건이 empty_or_invalid_json(복불복)이었다. 실패 시 원문 앞부분을
    # llm_error에 남겨 '무엇이 왔는지'를 사후 판독 가능하게 한다.
    parsed: dict[str, object] = {}
    raw_text = ""
    last_error = ""
    for attempt in range(2):
        try:
            response = _get_adapter().Generate(
                LlmRequest(
                    user_prompt=user_prompt,
                    system_prompt=_IDENTITY_SYSTEM_PROMPT,
                    generation_options=LlmGenerationOptions(temperature=0, max_tokens=tokens),
                ),
            )
            raw_text = str(getattr(response, "generatedText", ""))
            parsed = _extract_json(raw_text)
        except Exception as error:  # noqa: BLE001 — fallback to regex only
            last_error = f"{type(error).__name__}: {error}"
            parsed = {}
        if parsed:
            break

    if not parsed:
        return {
            "understanding_mode": "llm_fallback",
            "llm_error": (
                f"empty_or_invalid_json(retried) raw[:200]={raw_text[:200]!r}"
                if not last_error else f"{last_error} (retried)"
            ),
        }

    chapterHintTerms = _dedup_strings(
        parsed.get("chapter_hint_terms"),
        limit=8,
    )
    chapterHintSourceTerms = _dedup_strings(
        parsed.get("chapter_hint_source_terms"),
        limit=8,
    )

    try:
        confidence = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    return {
        "translated_product_name": str(parsed.get("translated_product_name") or "").strip(),
        "commercial_identity": str(
            parsed.get("commercial_identity")
            or distilledIdentity.commercialIdentity
            or productName
        ).strip(),
        "normalized_tariff_description": str(
            parsed.get("normalized_tariff_description")
            or distilledIdentity.normalizedDescription
        ).strip(),
        "identity_terms": _dedup_strings(
            parsed.get("identity_terms") or distilledIdentity.identityTerms,
            limit=16,
        ),
        "product_form_terms": _dedup_strings(
            parsed.get("product_form_terms")
            or (
                *distilledIdentity.productFormSignalTerms,
                *distilledIdentity.processingSignalTerms,
            ),
            limit=20,
        ),
        "ingredient_class": _grounded_typed_field(parsed.get("ingredient_class")),
        # 주/부성분: 사실 보고(성분 서열)로 한정 — 소비층에서 결정론 근거와
        # 합류(결정론 우선, LLM 단독 확정 불가). ASAP_IDENTITY_PRINCIPAL=0 비활성.
        "principal_ingredient_guess": (
            str(parsed.get("principal_ingredient_guess") or "").strip().lower()[:40]
            if (os.environ.get("ASAP_IDENTITY_PRINCIPAL", "1") or "1").strip() != "0" else ""
        ),
        "accessory_ingredients": _dedup_strings(
            parsed.get("accessory_ingredients"), limit=8,
        ) if (os.environ.get("ASAP_IDENTITY_PRINCIPAL", "1") or "1").strip() != "0" else (),
        "food_form": _grounded_typed_field(parsed.get("food_form")),
        "processing_state": _grounded_typed_field(parsed.get("processing_state")),
        "domain_hints": tuple(
            term
            for term in _dedup_strings(parsed.get("domain_hints"), limit=6)
            if term in DOMAIN_HINT_VOCAB
        )[:6],
        "chapter_hint_terms": chapterHintTerms,
        "chapter_hint_source_terms": chapterHintSourceTerms,
        "chapter_hint_basis": str(parsed.get("chapter_hint_basis") or "").strip()
        or ("from_chapter_context" if chapterHintTerms else "chapter_context_unavailable"),
        "chapter_hint_status": str(parsed.get("chapter_hint_status") or "").strip()
        or ("enabled" if chapterHintTerms else "not_enabled"),
        "confidence": confidence,
        "needs_review": bool(parsed.get("needs_review")),
        "understanding_mode": "llm_json",
        "llm_error": "",
    }
