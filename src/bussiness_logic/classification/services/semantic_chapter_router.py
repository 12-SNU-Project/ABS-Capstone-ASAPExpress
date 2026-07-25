"""Closed-choice HS2 routing over ProductUnderstanding facts and chapter law.

This experimental router deliberately has no keyword score.  The LLM selects an
ordered chapter decision from the finite ``cn_chapter_index`` authority cards;
code then validates every returned chapter and evidence pointer.  The selected
chapter is runtime authority, while alternatives are retained only for explicit
reopen.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

from bussiness_logic.bridge.schema import (
    LlmGenerationOptions,
    LlmRequest,
    LlmResponseFormat,
)
from bussiness_logic.classification.model.semantic_chapter_routing import (
    SemanticChapterRouteHint,
    SemanticChapterRoutingBasis,
)


_SYSTEM_PROMPT = """
You are the HS Chapter closed-choice decision component for EU customs
classification. Select from the supplied chapter authority cards only.

Rules:
1. Product facts are evidence. Chapter cards are classification authority.
2. Decide what the product is as presented, then consider material, processing,
   physical form, preservation and intended use.
3. Respect inclusion and exclusion text. Raw and prepared goods must not be
   conflated.
4. Never create a chapter, fact or legal clause. Do not use outside knowledge to
   replace missing product evidence.
5. Return an ordered candidate list. The first candidate is selected; later
   candidates are alternatives only. Do not emit numeric scores or confidence.
6. Every candidate must cite non-empty product fact paths and authority fields
   from the supplied objects. If evidence is insufficient, return unresolved.

Return exactly one JSON object with this shape:
{
  "decision_status": "selected|ambiguous|unresolved",
  "candidates": [
    {
      "chapter": "NN",
      "support_status": "supported|possible",
      "reason": "short reason",
      "fact_paths": ["identity_hints.food_form"],
      "authority_fields": ["chapter_including"],
      "missing_facts": []
    }
  ],
  "rejected_chapters": [
    {"chapter": "NN", "reason": "short authority-based reason"}
  ]
}
""".strip()

_FACT_PATHS = (
    "product_name",
    "identity_hints.commercial_identity",
    "identity_hints.normalized_tariff_description",
    "identity_hints.ingredient_class",
    "identity_hints.food_form",
    "identity_hints.processing_state",
    "identity_hints.preservation_state",
    "identity_hints.physical_form",
    "identity_hints.intended_use",
    "identity_hints.principal_ingredient_guess",
    "identity_hints.identity_terms",
    "identity_hints.product_form_terms",
    "composition_facts.principal_ingredient",
    "composition_facts.principal_ingredient_status",
    "composition_facts.ingredient_classes",
    "composition_facts.ingredient_entries",
    "composition_facts.ingredient_percentages",
    "composition_facts.processing_state",
    "composition_facts.preservation_state",
    "composition_facts.physical_form",
    "composition_facts.contains_wrapper_or_dough",
    "composition_facts.contains_sauce_or_broth",
)

_AUTHORITY_FIELDS = frozenset({
    "chapter_title",
    "chapter_including",
    "chapter_excluding",
    "allowed_processing_scope",
    "classification_decision_axes",
    "routing_guardrails",
    "prepared_food_redirect_chapters",
})


_CHAPTER_DOMAIN_FALLBACK: dict[str, tuple[str, ...]] = {
    **{
        chapter: ("food",)
        for chapter in (
            "06", "07", "08", "09", "10", "11", "12", "13", "14", "15",
            "17", "18", "19", "20", "21", "22", "24",
        )
    },
    **{
        chapter: ("food", "animal_origin")
        for chapter in ("02", "03", "04", "16", "23")
    },
    "01": ("animal_origin",),
    "05": ("animal_origin",),
    "33": ("cosmetics",),
}


def _ReadPath(data: Mapping[str, object], path: str) -> object:
    value: object = data
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _HasValue(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "unknown", "undetermined", "none", "null"}
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _Clip(value: object, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _CompactEntry(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    keep = (
        "ingredient_name", "ingredient", "name_en", "component", "scope",
        "percent", "percentage", "order_index", "class", "ingredient_class",
        "role", "source", "source_kind",
    )
    out = {key: value.get(key) for key in keep if _HasValue(value.get(key))}
    return out or None


def _CanonicalFactPath(value: object) -> str:
    """Accept the model's harmless wrapper prefix, then validate canonically."""
    path = str(value or "").strip()
    prefix = "product_facts."
    while path.startswith(prefix):
        path = path[len(prefix):]
    return path


def BuildHs2EvidenceProjection(
    productUnderstanding: Mapping[str, object],
) -> dict[str, object]:
    """Project only typed, auditable ProductUnderstanding facts for HS2."""

    identity = productUnderstanding.get("identity_hints")
    if not isinstance(identity, Mapping):
        identity = {}
    composition = productUnderstanding.get("composition_facts")
    if not isinstance(composition, Mapping):
        composition = {}

    rawEntries = [
        raw for raw in list(composition.get("ingredient_entries") or [])
        if isinstance(raw, Mapping)
    ]
    coiEntries = [
        raw for raw in rawEntries
        if str(raw.get("source") or "").strip() == "coi_normalized"
    ]
    # COI is the composition authority. Reconstruction entries are a gap-fill
    # only and must not be presented to the router as equal competing facts.
    resolvedEntries = (
        coiEntries
        if str(composition.get("composition_provenance") or "") == "coi_normalized"
        and coiEntries
        else rawEntries
    )
    entries = [
        compact
        for raw in resolvedEntries[:10]
        for compact in (_CompactEntry(raw),)
        if compact
    ]
    percentages = [
        compact
        for raw in list(composition.get("ingredient_percentages") or [])[:10]
        for compact in (_CompactEntry(raw),)
        if compact
    ]
    compositionProjection = {
        key: composition.get(key)
        for key in (
            "principal_ingredient",
            "principal_ingredient_status",
            "ingredient_classes",
            "processing_state",
            "preservation_state",
            "physical_form",
        )
        if _HasValue(composition.get(key))
    }
    # A true structural flag is observed evidence. False is currently the DTO
    # default and means either absent or not detected, so it is not a negative.
    for key in ("contains_wrapper_or_dough", "contains_sauce_or_broth"):
        if composition.get(key) is True:
            compositionProjection[key] = True
    if entries:
        compositionProjection["ingredient_entries"] = entries
    if percentages:
        compositionProjection["ingredient_percentages"] = percentages

    return {
        "product_name": str(productUnderstanding.get("product_name") or "")[:160],
        "identity_hints": {
            key: identity.get(key)
            for key in (
                "commercial_identity",
                "normalized_tariff_description",
                "ingredient_class",
                "food_form",
                "processing_state",
                "preservation_state",
                "physical_form",
                "intended_use",
                "principal_ingredient_guess",
                "identity_terms",
                "product_form_terms",
            )
            if _HasValue(identity.get(key))
        },
        "composition_facts": compositionProjection,
    }


def BuildChapterAuthorityCards(
    chapterRows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, str], ...]:
    """Build compact legal cards without chapter keywords or ranking weights."""

    cards: list[dict[str, str]] = []
    for row in chapterRows:
        chapter = re.sub(r"\D", "", str(row.get("chapter") or ""))[:2]
        if not chapter:
            continue
        cards.append({
            "chapter": chapter.zfill(2),
            "chapter_title": _Clip(
                row.get("chapter_title") or row.get("title"), 180),
            "chapter_including": _Clip(
                row.get("chapter_including")
                or row.get("description")
                or row.get("heading_scope"), 520),
            "chapter_excluding": _Clip(row.get("chapter_excluding"), 360),
            "allowed_processing_scope": _Clip(
                row.get("allowed_processing_scope"), 180),
            "classification_decision_axes": _Clip(
                row.get("classification_decision_axes"), 180),
            "routing_guardrails": _Clip(row.get("routing_guardrails"), 260),
            "prepared_food_redirect_chapters": _Clip(
                row.get("prepared_food_redirect_chapters"), 80),
        })
    return tuple(sorted(cards, key=lambda card: card["chapter"]))


def _ExtractJson(text: str) -> dict[str, object]:
    raw = str(text or "").strip()
    if "```" in raw:
        raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip().rstrip("`").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if not (0 <= start < end):
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _StringList(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


class SemanticChapterRouter:
    """Select HS2 with one closed-choice LLM call and code validation."""

    def __init__(
        self,
        *,
        chapterRowsProvider,
        runtimeAdapter: object | None = None,
        maxTokens: int = 2048,
    ) -> None:
        self._chapterRowsProvider = chapterRowsProvider
        self._runtimeAdapter = runtimeAdapter
        self._maxTokens = max(1, maxTokens)

    def Route(
        self,
        productUnderstanding: Mapping[str, object],
    ) -> SemanticChapterRouteHint:
        rows = tuple(self._chapterRowsProvider())
        cards = BuildChapterAuthorityCards(rows)
        if not cards:
            return self._Failure("chapter_authority_cards_empty", rowCount=len(rows))

        projection = BuildHs2EvidenceProjection(productUnderstanding)
        if not _HasValue(projection.get("product_name")) and not (
            projection.get("identity_hints") or projection.get("composition_facts")
        ):
            return self._Failure("product_understanding_projection_empty", rowCount=len(rows))

        authorityPayload = json.dumps(cards, ensure_ascii=False, separators=(",", ":"))
        authorityHash = hashlib.sha256(authorityPayload.encode("utf-8")).hexdigest()[:16]
        promptPayload = {
            "product_facts": projection,
            "chapter_authority_cards": cards,
        }
        userPrompt = json.dumps(promptPayload, ensure_ascii=False, separators=(",", ":"))
        promptHash = hashlib.sha256(
            (_SYSTEM_PROMPT + "\n" + userPrompt).encode("utf-8")
        ).hexdigest()[:16]

        if self._runtimeAdapter is None:
            return self._Failure(
                "semantic_runtime_not_configured",
                rowCount=len(rows),
                promptHash=promptHash,
                authorityHash=authorityHash,
            )

        try:
            response = self._runtimeAdapter.Generate(
                LlmRequest(
                    user_prompt=userPrompt,
                    system_prompt=_SYSTEM_PROMPT,
                    response_format=LlmResponseFormat.JSON_OBJECT,
                    generation_options=LlmGenerationOptions(
                        temperature=0,
                        max_tokens=self._maxTokens,
                    ),
                )
            )
            parsed = _ExtractJson(str(getattr(response, "generatedText", "")))
        except Exception as error:  # noqa: BLE001 - unresolved, never score fallback
            return self._Failure(
                f"semantic_runtime_error:{type(error).__name__}:{error}",
                rowCount=len(rows),
                promptHash=promptHash,
                authorityHash=authorityHash,
            )

        validChapters = {card["chapter"] for card in cards}
        rowByChapter = {
            re.sub(r"\D", "", str(row.get("chapter") or ""))[:2].zfill(2): row
            for row in rows
        }
        validated: list[dict[str, object]] = []
        for rawCandidate in list(parsed.get("candidates") or [])[:5]:
            if not isinstance(rawCandidate, Mapping):
                continue
            chapter = re.sub(r"\D", "", str(rawCandidate.get("chapter") or ""))[:2]
            if chapter not in validChapters or any(
                item["chapter"] == chapter for item in validated
            ):
                continue
            factPaths = list(dict.fromkeys(
                path
                for rawPath in _StringList(rawCandidate.get("fact_paths"), 10)
                for path in (_CanonicalFactPath(rawPath),)
                if path in _FACT_PATHS
                and _HasValue(_ReadPath(projection, path))
            ))
            authorityFields = [
                field for field in _StringList(
                    rawCandidate.get("authority_fields"), 8)
                if field in _AUTHORITY_FIELDS
            ]
            if not factPaths or not authorityFields:
                continue
            authorityRow = rowByChapter.get(chapter, {})
            validated.append({
                "chapter": chapter,
                "chapter_description": _Clip(
                    authorityRow.get("chapter_title")
                    or authorityRow.get("title")
                    or authorityRow.get("description"),
                    320,
                ),
                "rank": len(validated) + 1,
                "selected": len(validated) == 0,
                "support_status": (
                    "supported"
                    if str(rawCandidate.get("support_status") or "").lower()
                    == "supported" else "possible"
                ),
                "reason": _Clip(rawCandidate.get("reason"), 320),
                "fact_bindings": [
                    {"path": path, "value": _ReadPath(projection, path)}
                    for path in factPaths
                ],
                "authority_bindings": authorityFields,
                "missing_facts": _StringList(
                    rawCandidate.get("missing_facts"), 8),
            })

        if not validated:
            return self._Failure(
                "semantic_response_has_no_valid_grounded_candidate",
                rowCount=len(rows),
                promptHash=promptHash,
                authorityHash=authorityHash,
                parsedDecision=parsed,
            )

        selected = str(validated[0]["chapter"])
        alternatives = tuple(str(item["chapter"]) for item in validated[1:])
        selectedRow = rowByChapter.get(selected, {})
        domainScopes = self._SplitValues(selectedRow.get("domain_scope_candidates"))
        if not domainScopes:
            domainScopes = list(_CHAPTER_DOMAIN_FALLBACK.get(selected, ()))
        preGateDomains = self._SplitValues(
            selectedRow.get("pre_gate_domain_candidates"))
        rejected = [
            {
                "chapter": re.sub(
                    r"\D", "", str(item.get("chapter") or ""))[:2],
                "reason": _Clip(item.get("reason"), 240),
            }
            for item in list(parsed.get("rejected_chapters") or [])[:8]
            if isinstance(item, Mapping)
            and re.sub(r"\D", "", str(item.get("chapter") or ""))[:2]
            in validChapters
        ]
        missingFacts = tuple(dict.fromkeys(
            str(value)
            for item in validated
            for value in list(item.get("missing_facts") or [])
            if str(value).strip()
        ))
        semanticDecision = {
            "decision_status": str(parsed.get("decision_status") or "selected"),
            "selected_hs2": selected,
            "alternative_hs2": list(alternatives),
            "candidates": validated,
            "rejected_chapters": rejected,
            "prompt_hash": promptHash,
            "authority_hash": authorityHash,
            "model_name": str(getattr(response, "modelName", "") or ""),
            "runtime_path": str(getattr(response, "runtimePath", "") or ""),
            "response_id": str(getattr(response, "responseId", "") or ""),
        }
        return SemanticChapterRouteHint(
            candidateHs2=(selected, *alternatives),
            blockedHs2=tuple(
                item["chapter"] for item in rejected
                if item["chapter"] not in {selected, *alternatives}
            ),
            domainScopes=tuple(domainScopes),
            preGateDomains=tuple(preGateDomains),
            routingBasis=SemanticChapterRoutingBasis(
                method="semantic_closed_choice_llm",
                sourceTable="cn_chapter_index",
                rowCount=len(rows),
            ),
            missingFacts=missingFacts,
            candidateChapterDetails=tuple(validated),
            selectedHs2=selected,
            alternativeHs2=alternatives,
            semanticDecision=semanticDecision,
        )

    @staticmethod
    def _SplitValues(value: object) -> list[str]:
        if isinstance(value, str):
            raw = re.split(r"[;,|]", value)
        elif isinstance(value, (list, tuple, set)):
            raw = list(value)
        else:
            raw = []
        return list(dict.fromkeys(
            str(item).strip() for item in raw if str(item).strip()
        ))

    @staticmethod
    def _Failure(
        reason: str,
        *,
        rowCount: int,
        promptHash: str = "",
        authorityHash: str = "",
        parsedDecision: Mapping[str, object] | None = None,
    ) -> SemanticChapterRouteHint:
        return SemanticChapterRouteHint(
            routingBasis=SemanticChapterRoutingBasis(
                method="semantic_closed_choice_llm_unresolved",
                blockedReason=reason,
                sourceTable="cn_chapter_index",
                rowCount=rowCount,
            ),
            semanticDecision={
                "decision_status": "unresolved",
                "error": reason,
                "prompt_hash": promptHash,
                "authority_hash": authorityHash,
                "parsed_decision": dict(parsedDecision or {}),
            },
        )
