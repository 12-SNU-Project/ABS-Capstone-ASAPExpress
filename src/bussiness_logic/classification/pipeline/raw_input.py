"""Classification raw input builders."""

from __future__ import annotations

from bussiness_logic.input_process.product_facts import (
    NormalizeProductFacts,
    PrepareUserInputFacts,
)
from bussiness_logic.product.pipeline.kurly_product_facts import (
    CollectKurlyProductFactsIfNeeded,
)
from bussiness_logic.utils.json_types import JsonObject


def BuildRawInputFromUi(
    *,
    query: str,
    facts: JsonObject,
) -> JsonObject:
    """Map UI/API text + product facts JSON into EvidenceIntakeComponent input."""
    preparedFacts = PrepareUserInputFacts(query=query, facts=facts)
    collectedFacts = CollectKurlyProductFactsIfNeeded(facts=preparedFacts)
    return BuildRawInputFromPreparedFacts(query=query, facts=collectedFacts)


def BuildRawInputFromPreparedFacts(
    *,
    query: str,
    facts: JsonObject,
) -> JsonObject:
    """Map prepared product facts into EvidenceIntakeComponent input."""
    normalizedFacts = NormalizeProductFacts(facts or {})
    sourceUrls = normalizedFacts.get("source_urls") or normalizedFacts.get("url") or []
    if isinstance(sourceUrls, str):
        sourceUrls = [sourceUrls] if sourceUrls.strip() else []

    ocrText = normalizedFacts.get("ocr_text") or []
    if isinstance(ocrText, str):
        ocrText = [ocrText] if ocrText.strip() else []
    inputReconstruction = normalizedFacts.get("input_reconstruction") or {}
    if not isinstance(inputReconstruction, dict):
        inputReconstruction = {}
    reconstructedProductFacts = (
        normalizedFacts.get("reconstructed_product_facts")
        or inputReconstruction.get("reconstructed_product_facts")
        or []
    )
    unresolvedProductFacts = (
        normalizedFacts.get("unresolved_product_facts")
        or inputReconstruction.get("unresolved_product_facts")
        or []
    )
    productFactConflicts = (
        normalizedFacts.get("product_fact_conflicts")
        or inputReconstruction.get("product_fact_conflicts")
        or []
    )
    reconstructedFactTexts = (
        normalizedFacts.get("reconstructed_fact_texts")
        or inputReconstruction.get("reconstructed_fact_texts")
        or []
    )
    userInputFacts = normalizedFacts.get("user_input_facts") or {}
    if not isinstance(userInputFacts, dict):
        userInputFacts = {}

    return {
        "product_name": normalizedFacts.get("product_name") or query,
        "description": (
            normalizedFacts.get("description")
            or normalizedFacts.get("short_description")
            or ""
        ),
        "composition": normalizedFacts.get("composition") or reconstructedFactTexts or [],
        "reconstructed_product_facts": reconstructedProductFacts,
        "unresolved_product_facts": unresolvedProductFacts,
        "product_fact_conflicts": productFactConflicts,
        "reconstructed_fact_texts": reconstructedFactTexts,
        "ocr_text": ocrText,
        "source_urls": sourceUrls,
        "ingredients": userInputFacts.get("ingredients") or [],
        "origin_country": (
            userInputFacts.get("origin_country")
            or normalizedFacts.get("origin_country")
            or "unknown"
        ),
        "intended_use": (
            userInputFacts.get("intended_use")
            or normalizedFacts.get("intended_use")
            or "unknown"
        ),
        "warnings": normalizedFacts.get("warnings") or [],
        "url_intake": normalizedFacts.get("url_intake") or {},
        "input_reconstruction": inputReconstruction,
    }
