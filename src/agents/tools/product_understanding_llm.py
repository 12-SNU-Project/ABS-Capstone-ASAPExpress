"""LLM combiner for ProductUnderstanding identity lane (baseline-styled, additive).

Restores the pre-baseline LLM combination step that the partial merge dropped:
multi-source Korean evidence (product name / OCR-reconstructed facts / Naver
encyclopedia) is combined by a bounded LLM into the *current* 2-lane
``DistilledIdentityFacts`` fields — it never emits HS/CN codes or routing
decisions, so hallucination stays contained to typed identity fields.

Design constraints:
  - Adapter goes through the bridge ``build_runtime_adapter`` (same path as
    StagedClassificationTool), so the runtime model is env-selected (gemini).
  - ``ingredient_class`` / ``food_form`` stay inside the existing closed
    vocabularies so the downstream StagedClassificationTool AXIS_MAP keeps
    matching; richer open-vocab signal lives in ``product_form_terms`` /
    ``identity_terms`` and the English ``normalized_tariff_description``.
  - Chapter-routing context is read from Supabase ``cn_chapter_index`` (no local
    data files). Degrades gracefully (never raises) to the regex distiller.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from agents.pipeline_dto import EncyclopediaEvidenceSet


# Closed vocabularies must mirror IdentityDistillerTool so both paths feed the
# same StagedClassificationTool axis map.
INGREDIENT_CLASS_VOCAB = ("mollusc", "cereal", "cosmetic", "other")
FOOD_FORM_VOCAB = ("noodle", "bread_pastry", "soup", "sauce", "cosmetic", "other")
PROCESSING_STATE_VOCAB = ("processed_or_prepared", "raw_or_fresh", "unknown")
DOMAIN_HINT_VOCAB = ("food", "cosmetics", "pharmaceutical", "hazardous", "animal_origin", "other")

_IDENTITY_SYSTEM_PROMPT = f"""
Return only one JSON object. No markdown, no code fence.
You are ProductUnderstandingTool. Combine the given product evidence into
chapter-routing identity facts. Do NOT output HS/CN/TARIC codes or documents.

Rules:
- Use only the supplied evidence. Do not invent ingredients or forms.
- Allergen / cross-contact / manufacturer / country / expiry / package text is
  admin label evidence, not product form.
- Translate the Korean product into an English commercial/tariff identity and a
  concise HS/CN tariff-nomenclature description (physical form, processing state,
  the ingredient giving essential character).
- ingredient_class MUST be one of: {", ".join(INGREDIENT_CLASS_VOCAB)}.
- food_form MUST be one of: {", ".join(FOOD_FORM_VOCAB)}.
- processing_state MUST be one of: {", ".join(PROCESSING_STATE_VOCAB)}.
- domain_hints values MUST be from: {", ".join(DOMAIN_HINT_VOCAB)}.
- product_form_terms are open English tariff-form phrases (e.g. "prepared rice
  meal", "cereal preparation", "stir-fried"), used to enrich routing.

JSON keys (all required):
translated_product_name, commercial_identity, normalized_tariff_description,
ingredient_class, food_form, processing_state, identity_terms, composition_terms,
processing_terms, product_form_terms, domain_hints, confidence, needs_review.
""".strip()

_TRANSLATION_SYSTEM_PROMPT = (
    "You are a customs tariff classification assistant. Convert a Korean "
    "food/cosmetic product into ONE concise English sentence phrased in HS/CN "
    "tariff nomenclature vocabulary (physical form, processing/preparation "
    "state, and the single ingredient giving the essential character). Output "
    "only that English description. No HS/CN codes, no commentary, no Korean."
)

_adapter_cache: list[Any] = []
_chapter_context_cache: list[str] = []


def _get_adapter() -> Any:
    if not _adapter_cache:
        from agents._external_classifier import build_runtime_adapter

        _adapter_cache.append(build_runtime_adapter())
    return _adapter_cache[0]


def _extract_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if "```" in raw:
        raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _chapter_context() -> str:
    """Compact chapter-routing context from Supabase cn_chapter_index (no files)."""
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
                or ""
            ).strip()
            if chapter and title:
                lines.append(f"{chapter}: {title[:90]}")
    except Exception:  # noqa: BLE001 — context is best-effort
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
        f"- {entry.title}: {entry.description[:200]}"
        for entry in encyclopediaEvidence.entries[:3]
    )
    return (
        f"product_name: {productName}\n"
        f"description: {shortDescription}\n\n"
        f"classification_relevant_evidence:\n{facts or '-'}\n\n"
        f"encyclopedia_evidence:\n{encyc or '-'}"
    )


def _coerce_enum(value: Any, vocab: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in vocab else default


def _string_tuple(value: Any, *, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
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
) -> dict[str, Any]:
    """Combine evidence into current-schema identity fields via one LLM call.

    Returns a dict with the DistilledIdentityFacts-shaped keys plus
    ``understanding_mode``/``needs_review``/``llm_error``. On any failure the
    dict is empty except ``llm_error`` so the caller falls back to the regex
    distiller. Never raises.
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
            )
        )
        parsed = _extract_json(getattr(response, "generatedText", "") or "")
    except Exception as exc:  # noqa: BLE001 — degrade to regex distiller
        return {"understanding_mode": "regex_fallback", "llm_error": f"{type(exc).__name__}: {exc}"}
    if not parsed:
        return {"understanding_mode": "regex_fallback", "llm_error": "empty_or_invalid_json"}

    try:
        confidence = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "translated_product_name": str(parsed.get("translated_product_name") or "").strip(),
        "commercial_identity": str(parsed.get("commercial_identity") or productName).strip(),
        "normalized_tariff_description": str(parsed.get("normalized_tariff_description") or "").strip(),
        "ingredient_class": _coerce_enum(parsed.get("ingredient_class"), INGREDIENT_CLASS_VOCAB, "other"),
        "food_form": _coerce_enum(parsed.get("food_form"), FOOD_FORM_VOCAB, "other"),
        "processing_state": _coerce_enum(parsed.get("processing_state"), PROCESSING_STATE_VOCAB, "unknown"),
        "identity_terms": _string_tuple(parsed.get("identity_terms"), limit=16),
        "composition_terms": _string_tuple(parsed.get("composition_terms"), limit=20),
        "processing_terms": _string_tuple(parsed.get("processing_terms"), limit=12),
        "product_form_terms": _string_tuple(parsed.get("product_form_terms"), limit=20),
        "domain_hints": tuple(
            h for h in _string_tuple(parsed.get("domain_hints"), limit=6) if h in DOMAIN_HINT_VOCAB
        ),
        "confidence": confidence,
        "needs_review": bool(parsed.get("needs_review")),
        "understanding_mode": "llm_json",
        "llm_error": "",
    }


def TranslateToTariffEnglish(productName: str, factTexts: list[str]) -> str:
    """Korean product facts -> one tariff-nomenclature English sentence ("" on failure)."""
    facts = "; ".join(t for t in factTexts[:20] if str(t).strip())
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
            )
        )
        return (getattr(response, "generatedText", "") or "").strip()
    except Exception:  # noqa: BLE001 — translation is best-effort
        return ""
