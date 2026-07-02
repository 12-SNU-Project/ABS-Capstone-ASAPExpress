"""LLM combiner for ProductUnderstanding identity lane.

Baseline-styled, additive path:
  - multi-source Korean evidence (product name / OCR-reconstructed facts / Wikipedia evidence)
  - constrained JSON-completion by Chapter-boundary vocabulary

The combiner never emits HS/CN codes or direct routing decisions; it only enriches
current ``DistilledIdentityFacts`` fields and routing hint terms.
"""

from __future__ import annotations

import json
import os
import re

from agents.pipeline_dto import EncyclopediaEvidenceSet


INGREDIENT_CLASS_VOCAB = ("mollusc", "cereal", "cosmetic", "other")
FOOD_FORM_VOCAB = ("noodle", "bread_pastry", "soup", "sauce", "cosmetic", "other")
PROCESSING_STATE_VOCAB = ("processed_or_prepared", "raw_or_fresh", "unknown")
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
You are ProductUnderstandingTool. Combine the given product evidence into
chapter-routing identity facts and bounded lexical hints. Do NOT output HS/CN/TARIC
codes or documents.

Rules:
- Use only the supplied evidence. Do not invent ingredients or forms.
- If the product description contains translated/common-English wording, keep it short
  and stable.
- Translate the product into tariff-style English wording where possible.
- ingredient_class MUST be one of: {", ".join(INGREDIENT_CLASS_VOCAB)}.
- food_form MUST be one of: {", ".join(FOOD_FORM_VOCAB)}.
- processing_state MUST be one of: {", ".join(PROCESSING_STATE_VOCAB)}.
- domain_hints values MUST be subset of: {", ".join(DOMAIN_HINT_VOCAB)}.

Use the provided chapter-boundary context (cn_chapter_index titles/keywords) to
propose up to 8 chapter_hint_terms. Each term should be a short English or
Korean keyword phrase that appears in those contexts.

JSON keys (all required):
translated_product_name, commercial_identity, normalized_tariff_description,
ingredient_class, food_form, processing_state, identity_terms,
composition_terms, processing_terms, product_form_terms, domain_hints,
chapter_hint_terms, chapter_hint_source_terms, chapter_hint_basis,
chapter_hint_status, confidence, needs_review.
""".strip()

_TRANSLATION_SYSTEM_PROMPT = (
    "You are a customs tariff classification assistant. Convert a Korean product "
    "into ONE concise English tariff-style sentence phrased with physical form, "
    "processing/preparation state, and the ingredient giving essential character. "
    "Output only that English description. No HS/CN codes, no commentary, no Korean."
)


_adapter_cache: list[object] = []
_chapter_context_cache: list[str] = []


def _get_adapter() -> object:
    if not _adapter_cache:
        from agents._external_classifier import build_runtime_adapter

        _adapter_cache.append(build_runtime_adapter())
    return _adapter_cache[0]


def _extract_json(text: str) -> dict[str, object]:
    raw = str(text or "").strip()
    if "```" in raw:
        raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
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
            title = str(
                row.get("title")
                or row.get("description")
                or row.get("heading_scope")
                or "",
            ).strip()
            keywords = str(row.get("chapter_keywords") or "").strip()
            if chapter and (title or keywords):
                scope = " | ".join(part for part in (title, keywords) if part)
                lines.append(f"{chapter}: {scope}".rstrip())
    except Exception:  # noqa: BLE001 — best-effort context build
        lines = []

    context = "cn_chapter_index (chapter: scope):\n" + "\n".join(lines[:97]) if lines else ""
    _chapter_context_cache.append(context)
    return context


def _compact_evidence(
    *,
    productName: str,
    shortDescription: str,
    factTexts: list[str],
    encyclopediaEvidence: EncyclopediaEvidenceSet,
) -> str:
    facts = "\n".join(f"- {t[:350]}" for t in factTexts[:10] if str(t).strip())
    encyc = "\n".join(
        f"- {entry.title}: {entry.description[:220]}"
        for entry in encyclopediaEvidence.entries[:3]
    )
    return (
        f"product_name: {productName}\n"
        f"description: {shortDescription}\n\n"
        f"classification_relevant_evidence:\n{facts or '-'}\n\n"
        f"encyclopedia_evidence:\n{encyc or '-'}"
    )


def _coerce_enum(value: object, vocab: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in vocab else default


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


def _filter_chapter_terms(
    values: tuple[str, ...],
    context: str,
    *,
    limit: int,
) -> tuple[str, ...]:
    if not context:
        return values[:limit]

    normalizedContext = context.lower()
    out: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value.strip().lower())
        if not normalized:
            continue
        if normalized not in normalizedContext:
            continue
        if normalized not in out:
            out.append(normalized)
        if len(out) >= limit:
            break
    return tuple(out)


def BuildIdentityFactsFromLlm(
    *,
    productName: str,
    shortDescription: str,
    factTexts: list[str],
    encyclopediaEvidence: EncyclopediaEvidenceSet,
    max_tokens: int | None = None,
) -> dict[str, object]:
    """Combine evidence into identity fields via one LLM call.

    Returns a dict keyed by ``DistilledIdentityFacts`` fields plus
    understanding mode + error fields. On failure returns a best-effort failure
    payload; caller overlays regex identity.
    """
    from bussiness_logic.bridge.schema import LlmGenerationOptions, LlmRequest

    tokens = max_tokens if max_tokens is not None else int(
        os.environ.get("ASAP_PRODUCT_UNDERSTANDING_MAX_TOKENS", "1200")
    )
    user_prompt = _compact_evidence(
        productName=productName,
        shortDescription=shortDescription,
        factTexts=factTexts,
        encyclopediaEvidence=encyclopediaEvidence,
    )
    chapter_context = _chapter_context()
    if chapter_context:
        user_prompt = f"{user_prompt}\n\n{chapter_context}"
    try:
        response = _get_adapter().Generate(
            LlmRequest(
                user_prompt=user_prompt,
                system_prompt=_IDENTITY_SYSTEM_PROMPT,
                generation_options=LlmGenerationOptions(temperature=0, max_tokens=tokens),
            ),
        )
        parsed = _extract_json(str(getattr(response, "generatedText", "")))
    except Exception as error:  # noqa: BLE001 — fallback to regex only
        return {
            "understanding_mode": "llm_fallback",
            "llm_error": f"{type(error).__name__}: {error}",
        }

    if not parsed:
        return {
            "understanding_mode": "llm_fallback",
            "llm_error": "empty_or_invalid_json",
        }

    chapterHintTerms = _dedup_strings(
        parsed.get("chapter_hint_terms"),
        limit=10,
    )
    chapterHintTerms = _filter_chapter_terms(chapterHintTerms, chapter_context, limit=8)
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
        "commercial_identity": str(parsed.get("commercial_identity") or productName).strip(),
        "normalized_tariff_description": str(parsed.get("normalized_tariff_description") or "").strip(),
        "ingredient_class": _coerce_enum(
            parsed.get("ingredient_class"),
            INGREDIENT_CLASS_VOCAB,
            "other",
        ),
        "food_form": _coerce_enum(
            parsed.get("food_form"),
            FOOD_FORM_VOCAB,
            "other",
        ),
        "processing_state": _coerce_enum(
            parsed.get("processing_state"),
            PROCESSING_STATE_VOCAB,
            "unknown",
        ),
        "identity_terms": _dedup_strings(parsed.get("identity_terms"), limit=16),
        "composition_terms": _dedup_strings(parsed.get("composition_terms"), limit=20),
        "processing_terms": _dedup_strings(parsed.get("processing_terms"), limit=12),
        "product_form_terms": _dedup_strings(parsed.get("product_form_terms"), limit=20),
        "domain_hints": tuple(
            term
            for term in _dedup_strings(parsed.get("domain_hints"), limit=6)
            if term in DOMAIN_HINT_VOCAB
        )[:6],
        "chapter_hint_terms": chapterHintTerms,
        "chapter_hint_source_terms": chapterHintSourceTerms,
        "chapter_hint_basis": str(parsed.get("chapter_hint_basis") or "").strip()
        or ("from_chapter_context" if chapterHintTerms else "context_fallback"),
        "chapter_hint_status": str(parsed.get("chapter_hint_status") or "").strip()
        or ("enabled" if chapterHintTerms else "not_enabled"),
        "confidence": confidence,
        "needs_review": bool(parsed.get("needs_review")),
        "understanding_mode": "llm_json",
        "llm_error": "",
    }


def TranslateToTariffEnglish(productName: str, factTexts: list[str]) -> str:
    """Korean product facts -> one tariff-nomenclature English sentence."""
    facts = "; ".join(text for text in factTexts[:20] if str(text).strip())
    if not (productName.strip() or facts.strip()):
        return ""
    from bussiness_logic.bridge.schema import LlmGenerationOptions, LlmRequest

    try:
        response = _get_adapter().Generate(
            LlmRequest(
                user_prompt=(
                    f"Korean product: {productName}\n"
                    f"Facts/ingredients: {facts}\n"
                    "Tariff-style English description:"
                ),
                system_prompt=_TRANSLATION_SYSTEM_PROMPT,
                generation_options=LlmGenerationOptions(temperature=0, max_tokens=200),
            ),
        )
        return str(getattr(response, "generatedText", "") or "").strip()
    except Exception:  # noqa: BLE001 — translation is best-effort
        return ""
