"""Product facts normalization for pipeline input."""

from __future__ import annotations

from bussiness_logic.utils.json_types import JsonObject


def PrepareUserInputFacts(
    *,
    query: str,
    facts: JsonObject,
) -> JsonObject:
    """Normalize UI/API facts and optional cached product-input artifact."""
    normalizedFacts = NormalizeProductFacts(facts or {})
    if normalizedFacts.get("use_cached_product_input"):
        productIdentifier = str(
            normalizedFacts.get("url")
            or normalizedFacts.get("product_id")
            or query
            or ""
        ).strip()
        try:
            from bussiness_logic.pipeline.export_requirement_pipeline import (
                LoadCachedProductInputFacts,
            )

            cachedFacts = LoadCachedProductInputFacts(productIdentifier)
            merged = dict(normalizedFacts)
            for key, value in cachedFacts.items():
                if value not in ("", [], None):
                    merged[key] = value
            merged["use_cached_product_input"] = True
            normalizedFacts = NormalizeProductFacts(merged)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"cached_product_input_not_found: {exc}") from exc
    return normalizedFacts


def NormalizeProductFacts(facts: JsonObject) -> JsonObject:
    """Normalize explicit Product facts payloads."""
    if not isinstance(facts, dict):
        return {}
    return NormalizeKurlyResultFacts(facts)


def NormalizeKurlyResultFacts(facts: JsonObject) -> JsonObject:
    """Flatten current Kurly URL intake result shape into Product facts."""
    if not isinstance(facts, dict):
        return {}
    parsed = facts.get("source_product_page") or {}
    if not isinstance(parsed, dict):
        parsed = {}
    inputReconstruction = facts.get("input_reconstruction") or {}
    if not isinstance(inputReconstruction, dict):
        inputReconstruction = {}

    factTexts = (
        facts.get("reconstructed_fact_texts")
        or inputReconstruction.get("reconstructed_fact_texts")
        or []
    )
    if not isinstance(factTexts, list):
        factTexts = []
    reconstructedProductFacts = (
        facts.get("reconstructed_product_facts")
        or inputReconstruction.get("reconstructed_product_facts")
        or []
    )
    unresolvedProductFacts = (
        facts.get("unresolved_product_facts")
        or inputReconstruction.get("unresolved_product_facts")
        or []
    )
    productFactConflicts = (
        facts.get("product_fact_conflicts")
        or inputReconstruction.get("product_fact_conflicts")
        or []
    )
    combinedOcrText = facts.get("combined_ocr_text") or ""
    ocrText: list[str] = []
    if isinstance(combinedOcrText, str) and combinedOcrText.strip():
        ocrText.append(combinedOcrText)
    if isinstance(factTexts, list):
        ocrText.extend(str(text) for text in factTexts if str(text).strip())

    productPageUrl = (
        facts.get("product_page_url")
        or parsed.get("product_page_url")
        or facts.get("url")
    )
    productName = facts.get("product_name") or parsed.get("product_name")
    shortDescription = (
        facts.get("short_description")
        or parsed.get("short_description")
        or facts.get("description")
    )
    productDomain = facts.get("product_domain") or parsed.get("product_domain")

    flattened = dict(facts)
    flattened.update({
        "url": productPageUrl or facts.get("url") or "",
        "product_name": productName or "",
        "description": shortDescription or "",
        "short_description": shortDescription or "",
        "product_domain": productDomain or facts.get("product_domain") or "unknown",
        "product_category": facts.get("product_category") or productDomain or "unknown",
        "brand_name": facts.get("brand_name") or parsed.get("brand_name") or "",
        "package_type": facts.get("package_type") or parsed.get("package_type") or "",
        "sale_unit": facts.get("sale_unit") or parsed.get("sale_unit") or "",
        "ocr_text": ocrText or facts.get("ocr_text") or [],
        "reconstructed_product_facts": reconstructedProductFacts,
        "unresolved_product_facts": unresolvedProductFacts,
        "product_fact_conflicts": productFactConflicts,
        "reconstructed_fact_texts": factTexts,
    })
    return flattened
