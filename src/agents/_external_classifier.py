"""
agents/_external_classifier — adapter for the vendored Stage 1 classifier.

The classifier runtime code lives in ``src/bussiness_logic``. It reads our core
data from ``docs/ASAP_Ontology_v1`` and orchestrates
its 7-step Stage 1 pipeline:

  1. ProductEvidenceState                → ProductClassificationInput
  2. CnCandidateRetriever.FindCandidates(...)
  3. OntologyContextBuilder.BuildContext(...)
  4. Stage1EvidencePackageBuilder.Build(...)
  5. Stage1RequestBuilder.BuildRequest(...)   → LlmRequest
  6. RuntimeAdapter.Generate(request)         → LlmResponse
  7. Stage1ResponseValidator + Stage1DecisionPolicy + Stage1TraversalController
     + Stage1RecommendationReportBuilder

Outputs collected into ExternalClassificationResult so ClassificationAgent
can stamp citations / reasoning / candidates onto the Blackboard.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field, is_dataclass, replace
from pathlib import Path
from typing import Any, Sequence


def _copy_with_clamped_max_tokens(request: Any, max_tokens: int) -> Any:
    """Return a copy of ``request`` whose generationOptions.maxTokens == max_tokens.

    Works for both the legacy ``@dataclass(frozen=True)`` LlmRequest /
    LlmGenerationOptions and the current pydantic ``BaseModel`` versions.
    """
    options = request.generationOptions
    if hasattr(options, "model_copy"):
        clamped_options = options.model_copy(update={"maxTokens": max_tokens})
    elif is_dataclass(options):
        clamped_options = replace(options, maxTokens=max_tokens)
    else:
        raise TypeError(
            f"Unsupported LlmGenerationOptions type: {type(options).__name__}"
        )
    if hasattr(request, "model_copy"):
        return request.model_copy(update={"generationOptions": clamped_options})
    if is_dataclass(request):
        return replace(request, generationOptions=clamped_options)
    raise TypeError(f"Unsupported LlmRequest type: {type(request).__name__}")


def _copy_with_prompts(
    request: Any,
    *,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    context_chunks: list[str] | None = None,
) -> Any:
    updates: dict[str, Any] = {}
    if system_prompt is not None:
        updates["systemPrompt"] = system_prompt
    if user_prompt is not None:
        updates["userPrompt"] = user_prompt
    if context_chunks is not None:
        updates["contextChunks"] = context_chunks
    if hasattr(request, "model_copy"):
        return request.model_copy(update=updates)
    if is_dataclass(request):
        return replace(request, **updates)
    raise TypeError(f"Unsupported LlmRequest type: {type(request).__name__}")


def _candidate_code(candidate: Any, *names: str) -> str:
    for name in names:
        value = getattr(candidate, name, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _build_candidate_contract(candidates: Sequence[Any]) -> list[dict[str, Any]]:
    contract: list[dict[str, Any]] = []
    for candidate in candidates:
        hs8 = _candidate_code(candidate, "hs8", "hs8Code")
        if not hs8:
            continue
        description = (
            getattr(candidate, "hs8Description", None)
            or getattr(candidate, "combinedDescription", None)
            or getattr(candidate, "candidateContextText", None)
            or ""
        )
        branch_context = getattr(candidate, "branchContext", None) or ""
        contract.append({
            "hs8": hs8,
            "hs6_code": _candidate_code(candidate, "hs6Code") or None,
            "cn8_description": str(description)[:300],
            "branch_context": str(branch_context)[:240],
            "path_codes": {
                "hs2": _candidate_code(candidate, "hs2Code") or None,
                "hs4": _candidate_code(candidate, "hs4Code") or None,
                "hs6": _candidate_code(candidate, "hs6Code") or None,
                "cn8": _candidate_code(candidate, "hs8Code", "hs8") or hs8,
            },
            "required_candidate_evidence_ref": f"cn_candidate:{hs8}",
        })
    return contract


def _build_stage1_response_skeleton(candidates: Sequence[Any]) -> dict[str, Any]:
    reviews: list[dict[str, Any]] = []
    for item in _build_candidate_contract(candidates):
        path_codes = item["path_codes"]
        reviews.append({
            "hs8": item["hs8"],
            "hs6_code": item["hs6_code"],
            "status": "possible_candidate",
            "supporting_product_facts": ["string"],
            "conflicting_or_exclusion_facts": [],
            "missing_information": ["string"],
            "evidence_refs": [item["required_candidate_evidence_ref"]],
            "classification_path_review": {
                "hs2": {
                    "code": path_codes["hs2"],
                    "consistency": "needs_review",
                    "comment": "string",
                },
                "hs4": {
                    "code": path_codes["hs4"],
                    "consistency": "needs_review",
                    "comment": "string",
                },
                "hs6": {
                    "code": path_codes["hs6"],
                    "consistency": "needs_review",
                    "comment": "string",
                },
                "cn8": {
                    "code": path_codes["cn8"],
                    "consistency": "needs_review",
                    "comment": "string",
                },
            },
            "classification_rule_review": {
                "include_rule_comment": "string",
                "exclude_rule_comment": "string",
                "hard_condition_comment": "string",
            },
            "similar_ebti_cases": [],
            "reason": "string",
            "human_review_required": True,
        })
    return {
        "classification_result": {
            "product_name": "string",
            "product_domain": "food_16_21 input domain value exactly as supplied if validator expects it",
            "domain_scopes": ["string"],
            "candidate_reviews": reviews,
            "not_enough_information": [],
            "recommended_next_action": "human_review_required",
            "human_review_warning": "This is a candidate review only, not a final customs determination.",
        }
    }


def _build_strict_stage1_prompt_suffix(
    product_input: Any,
    candidates: Sequence[Any],
) -> str:
    candidate_contract = _build_candidate_contract(candidates)
    skeleton = _build_stage1_response_skeleton(candidates[: min(len(candidates), 5)])
    return "\n".join([
        "",
        "STRICT_OUTPUT_CONTRACT_FOR_GEMMA4_CTX:",
        "Return exactly one valid JSON object. Do not return markdown, prose, comments, api_version, schema metadata, or an array root.",
        "The root object must contain only `classification_result`.",
        "Use the exact candidate hs8 codes below. Do not invent, normalize, or omit digits in reviewed candidates.",
        "Every candidate_review that you include must use one of these exact hs8 values and must cite its `required_candidate_evidence_ref` in evidence_refs.",
        "For every classification_path_review code, copy the code from path_codes exactly. If unsure about consistency, use `needs_review`, not a different enum.",
        "Allowed status values only: strong_candidate, possible_candidate, unlikely_candidate, insufficient_information.",
        "human_review_required must be the JSON boolean true for every candidate_review.",
        "product_domain must be exactly: {0}".format(product_input.productDomain),
        "domain_scopes must be exactly: {0}".format(json.dumps(product_input.domainScopes, ensure_ascii=False)),
        "candidate_contract:",
        json.dumps(candidate_contract, ensure_ascii=False, separators=(",", ":")),
        "minimal_shape_example:",
        json.dumps(skeleton, ensure_ascii=False, separators=(",", ":")),
    ])


def _harden_stage1_request(
    request: Any,
    product_input: Any,
    candidates: Sequence[Any],
) -> Any:
    system_suffix = "\n".join([
        "",
        "Hard output rule for local gemma4-ctx:",
        "You are filling a machine contract, not describing an API.",
        "Return only the requested classification_result JSON object.",
        "Never output api_version, api_version_info, OpenAPI-style schemas, explanations, or markdown fences.",
    ])
    user_suffix = _build_strict_stage1_prompt_suffix(product_input, candidates)
    return _copy_with_prompts(
        request,
        system_prompt=((request.systemPrompt or "").strip() + system_suffix).strip(),
        user_prompt=((request.userPrompt or "").strip() + user_suffix).strip(),
    )


def _build_repair_request(
    request: Any,
    product_input: Any,
    candidates: Sequence[Any],
    response_text: str,
    validation_report: Any,
) -> Any:
    issues = []
    for issue in getattr(validation_report, "issues", []) or []:
        issues.append({
            "severity": getattr(issue, "severity", ""),
            "issue_code": getattr(issue, "issueCode", ""),
            "field_path": getattr(issue, "fieldPath", ""),
            "message": getattr(issue, "message", ""),
        })
    repair_prompt = "\n".join([
        "Your previous answer did not satisfy the Stage 1 classification JSON contract.",
        "Rewrite it as one valid JSON object only. Do not include markdown or explanation.",
        _build_strict_stage1_prompt_suffix(product_input, candidates),
        "validator_issues:",
        json.dumps(issues[:20], ensure_ascii=False, separators=(",", ":")),
        "previous_response:",
        response_text[:3000],
    ])
    return _copy_with_prompts(request, user_prompt=repair_prompt)


def _build_compact_decision_request(
    request: Any,
    product_input: Any,
    candidates: Sequence[Any],
) -> Any:
    candidate_contract = _build_candidate_contract(candidates)
    classification_input_facts = list(
        getattr(product_input, "structuredProductFacts", []) or []
    )
    unresolved_facts = list(getattr(product_input, "unresolvedProductFacts", []) or [])
    fact_conflicts = list(getattr(product_input, "productFactConflicts", []) or [])
    classification_input_text_lines = list(
        getattr(product_input, "normalizedOcrFactTexts", []) or []
    )
    compact_shape = {
        "selected_hs8": "one exact candidate hs8 or null",
        "candidate_reviews": [
            {
                "hs8": "exact candidate hs8",
                "status": (
                    "strong_candidate|possible_candidate|unlikely_candidate|"
                    "insufficient_information"
                ),
                "reason": "short reason",
                "supporting_product_facts": ["short fact"],
                "conflicting_or_exclusion_facts": [],
                "missing_information": [],
            }
        ],
        "not_enough_information": [],
    }
    prompt = "\n".join([
        "Select the most plausible CN8 candidate for the product.",
        "Return exactly one JSON object only. Do not output a JSON schema.",
        "Do not use keys named type, properties, api_version, review_details, or data.",
        "Use only exact hs8 values from candidate_contract.",
        "If no candidate is plausible, set selected_hs8 to null.",
        "Do not select an ingredient-specific candidate unless that ingredient or condition is explicit in the product facts.",
        "For example, `Containing eggs` requires explicit egg/난/albumen/egg powder evidence; fish/meat/stuffed candidates require explicit matching evidence and percentage conditions.",
        "For instant ramen/noodle products described as 유탕면/라면/dried noodles with wheat flour and no explicit egg/stuffed/fish/meat percentage condition, prefer the dry/other noodle candidate over egg/stuffed/meat/fish candidates.",
        "Use classification_input_facts_json as the primary product facts for candidate review.",
        "classification_input_text_lines_json is OCR/detail-text evidence, not a substitute for structured facts.",
        "Do not infer facts that are not explicitly present in classification_input_facts_json.",
        "Use product type, physical form, processing state, storage state, ingredients, composition ratios, content weight, and origin facts when they are explicit.",
        "Use unlikely_candidate only when reconstructed product facts clearly contradict the candidate, or when the candidate requires an explicit essential condition that is absent from reconstructed facts.",
        "Do not mark a candidate as unlikely only because another candidate scores higher.",
        "If quantity, percentage, processing state, or composition condition is missing, use insufficient_information instead of unlikely_candidate.",
        "If a fact line appears contradictory or looks like OCR/reconstruction noise, mark the affected candidate as possible_candidate or insufficient_information instead of forcing a strong_candidate.",
        "Allowed status values: strong_candidate, possible_candidate, unlikely_candidate, insufficient_information.",
        "Review the strongest few candidates; unreviewed candidates will be filled deterministically as insufficient_information.",
        "product_name: {0}".format(product_input.productName or "unknown"),
        "product_domain: {0}".format(product_input.productDomain),
        "classification_input_text_line_count: {0}".format(
            len(classification_input_text_lines)
        ),
        "classification_input_facts_json:",
        json.dumps(
            classification_input_facts[:60],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "unresolved_product_facts_json:",
        json.dumps(unresolved_facts[:20], ensure_ascii=False, separators=(",", ":")),
        "product_fact_conflicts_json:",
        json.dumps(fact_conflicts[:20], ensure_ascii=False, separators=(",", ":")),
        "classification_input_text_lines_json:",
        json.dumps(
            classification_input_text_lines[:80],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "candidate_contract:",
        json.dumps(candidate_contract, ensure_ascii=False, separators=(",", ":")),
        "required_output_shape:",
        json.dumps(compact_shape, ensure_ascii=False, separators=(",", ":")),
    ])
    return _copy_with_prompts(request, user_prompt=prompt, context_chunks=[])


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    decoder = json.JSONDecoder()
    index = 0
    while index < len(stripped):
        start = stripped.find("{", index)
        if start < 0:
            return None
        try:
            value, end = decoder.raw_decode(stripped[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict):
            return value
        index = start + end
    return None


def _extract_compact_decision(
    text: str,
    candidates: Sequence[Any],
) -> dict[str, Any] | None:
    parsed = _extract_json_object(text)
    candidate_codes = {item["hs8"] for item in _build_candidate_contract(candidates)}
    if parsed is not None:
        selected = parsed.get("selected_hs8")
        if selected in candidate_codes or selected is None:
            return parsed

    # Salvage local-model outputs that start correctly but then degenerate
    # into repeated tokens before producing valid JSON.
    match = re.search(r'"selected_hs8"\s*:\s*"([0-9]{8})"', text or "")
    if match and match.group(1) in candidate_codes:
        selected_hs8 = match.group(1)
        return {
            "selected_hs8": selected_hs8,
            "candidate_reviews": [
                {
                    "hs8": selected_hs8,
                    "status": "possible_candidate",
                    "reason": (
                        "Recovered selected_hs8 from malformed compact LLM "
                        "response; full review generated deterministically."
                    ),
                    "supporting_product_facts": [],
                    "conflicting_or_exclusion_facts": [],
                    "missing_information": ["LLM compact JSON was malformed."],
                }
            ],
            "not_enough_information": ["LLM compact JSON was malformed."],
        }
    return None


def _apply_domain_selection_guard(
    compact: dict[str, Any],
    product_input: Any,
    candidates: Sequence[Any],
) -> dict[str, Any]:
    """Correct obvious local-LLM slips before Stage1 validator expansion."""
    candidate_codes = {item["hs8"] for item in _build_candidate_contract(candidates)}
    text = (product_input.BuildSearchText() or "").lower()
    if (
        "19023010" in candidate_codes
        and any(token in text for token in ("라면", "ramen", "instant noodle", "유탕면"))
        and not any(token in text for token in ("계란", "egg", "난백", "albumen"))
        and not any(token in text for token in ("stuffed", "filled pasta"))
    ):
        out = dict(compact)
        out["selected_hs8"] = "19023010"
        reviews = [
            item
            for item in out.get("candidate_reviews") or []
            if isinstance(item, dict) and item.get("hs8") != "19023010"
        ]
        reviews.insert(0, {
            "hs8": "19023010",
            "status": "strong_candidate",
            "reason": (
                "Domain guard: ramen/유탕면 evidence indicates dried/other "
                "noodles; no explicit egg, stuffed, fish, or meat percentage "
                "condition was provided."
            ),
            "supporting_product_facts": [
                "Product facts contain 라면/유탕면 and wheat-flour noodle evidence."
            ],
            "conflicting_or_exclusion_facts": [],
            "missing_information": [],
        })
        out["candidate_reviews"] = reviews
        return out
    return compact


def _copy_response_with_text(response: Any, generated_text: str) -> Any:
    if hasattr(response, "model_copy"):
        return response.model_copy(update={"generatedText": generated_text})
    if is_dataclass(response):
        return replace(response, generatedText=generated_text)
    raise TypeError(f"Unsupported LlmResponse type: {type(response).__name__}")


def _normalize_compact_status(value: Any) -> str:
    if value in {
        "strong_candidate",
        "possible_candidate",
        "unlikely_candidate",
        "insufficient_information",
    }:
        return str(value)
    return "insufficient_information"


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def _expand_compact_decision_to_stage1_json(
    compact: dict[str, Any],
    product_input: Any,
    candidates: Sequence[Any],
) -> str:
    candidate_contract = _build_candidate_contract(candidates)
    candidate_codes = {item["hs8"] for item in candidate_contract}
    selected_hs8 = compact.get("selected_hs8")
    if selected_hs8 not in candidate_codes:
        selected_hs8 = None

    review_by_hs8: dict[str, dict[str, Any]] = {}
    for review in compact.get("candidate_reviews") or []:
        if not isinstance(review, dict):
            continue
        hs8 = review.get("hs8")
        if hs8 in candidate_codes:
            review_by_hs8[str(hs8)] = review

    expanded_reviews: list[dict[str, Any]] = []
    for index, item in enumerate(candidate_contract):
        hs8 = item["hs8"]
        compact_review = review_by_hs8.get(hs8, {})
        if hs8 == selected_hs8:
            status = _normalize_compact_status(
                compact_review.get("status") or "strong_candidate"
            )
        elif compact_review:
            status = _normalize_compact_status(compact_review.get("status"))
        else:
            status = "insufficient_information"

        supporting = _list_of_strings(compact_review.get("supporting_product_facts"))
        conflicts = _list_of_strings(compact_review.get("conflicting_or_exclusion_facts"))
        missing = _list_of_strings(compact_review.get("missing_information"))
        reason = str(compact_review.get("reason") or "").strip()
        if not reason:
            if hs8 == selected_hs8:
                reason = "Selected as the most plausible CN8 candidate for human review."
            else:
                reason = "Not selected in the compact CN8 decision; retained only for audit."
        if not supporting and hs8 == selected_hs8:
            supporting = [product_input.BuildSearchText()[:300] or "Product facts support review."]
        if not missing and status == "insufficient_information":
            missing = ["More product composition/use details are required."]

        path_codes = item["path_codes"]

        def PathLevel(level: str) -> dict[str, Any]:
            return {
                "code": path_codes[level],
                "consistency": "needs_review",
                "comment": (
                    "Copied from candidate hierarchy; consistency remains subject to human review."
                ),
            }

        expanded_reviews.append({
            "hs8": hs8,
            "hs6_code": item["hs6_code"],
            "status": status,
            "supporting_product_facts": supporting,
            "conflicting_or_exclusion_facts": conflicts,
            "missing_information": missing,
            "evidence_refs": [item["required_candidate_evidence_ref"]],
            "classification_path_review": {
                "hs2": PathLevel("hs2"),
                "hs4": PathLevel("hs4"),
                "hs6": PathLevel("hs6"),
                "cn8": PathLevel("cn8"),
            },
            "classification_rule_review": {
                "include_rule_comment": "Reviewed against candidate include keywords where available.",
                "exclude_rule_comment": "No exclusion is finalized by the model; human review remains required.",
                "hard_condition_comment": "Hard conditions must be checked against product facts and official notes.",
            },
            "similar_ebti_cases": [],
            "reason": reason,
            "human_review_required": True,
        })

    payload = {
        "classification_result": {
            "product_name": product_input.productName or "unknown",
            "product_domain": product_input.productDomain,
            "domain_scopes": list(product_input.domainScopes),
            "candidate_reviews": expanded_reviews,
            "not_enough_information": _list_of_strings(
                compact.get("not_enough_information")
            ),
            "recommended_next_action": "human_review_required",
            "human_review_warning": (
                "This is a CN8 candidate review for human review, not a final "
                "legal/customs determination."
            ),
        }
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

# Max tokens for the LLM response. ASAPExpress default is 4096 which equals
# gemma4:26b's stock context window (4096) and causes ollama to abort mid-
# stream. With an 8192-context model (gemma4-ctx Modelfile override),
# 2048 leaves comfortable headroom for prompt + response.
LLM_MAX_TOKENS = 2048

ASAP_PROJECT_ROOT = Path(os.environ.get("ASAP_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
ASAP_SRC_ROOT = ASAP_PROJECT_ROOT / "src"
for _path in (ASAP_PROJECT_ROOT, ASAP_SRC_ROOT):
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from bussiness_logic.app_config import LoadAppConfig
from bussiness_logic.bridge.embedding import (
    BuildTextEmbeddingAdapter,
    BuildTextEmbeddingRuntimeConfig,
    ProbeTextEmbeddingDependency,
    TextEmbeddingAdapterBuildError,
    TextEmbeddingGenerationError,
)
from bussiness_logic.bridge.factory import BuildRuntimeAdapter
from bussiness_logic.bridge.probe import ProbeRuntimeDependency
from bussiness_logic.bridge.selector import (
    BuildDefaultLlmRuntimeConfig,
    BuildLlmRuntimeConfigFromEnv,
)
from bussiness_logic.core.classification.stage1 import (
    CnCandidateRetriever,
    ProductClassificationInput,
    Stage1EvidencePackageBuilder,
    Stage1RequestBuilder,
    Stage1ResponseValidator,
)
from bussiness_logic.core.context_retrieval.context_builder import (
    OntologyContextBuilder,
)
from bussiness_logic.core.context_retrieval.semantic_retrieval import (
    CnSemanticCandidateIndex,
)
from bussiness_logic.core.decision_flow.decision_policy import Stage1DecisionPolicy
from bussiness_logic.core.decision_flow.recommendation import (
    Stage1RecommendationReportBuilder,
)
from bussiness_logic.core.decision_flow.traversal import (
    Stage1TraversalController,
)
from bussiness_logic.core.classification.hierarchical_beam import (
    HierarchyBeamConfig,
)


APP_CONFIG = LoadAppConfig(ASAP_PROJECT_ROOT)
ASAP_ONTOLOGY_ROOT = APP_CONFIG.paths.ResolvePath(
    ASAP_PROJECT_ROOT,
    APP_CONFIG.paths.ontology_root,
)
ASAP_ENV_FILE = ASAP_PROJECT_ROOT / ".env"
SEMANTIC_CANDIDATE_INDEX: CnSemanticCandidateIndex | None = None
SEMANTIC_CANDIDATE_INDEX_STATUS: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Return container
# ---------------------------------------------------------------------------
@dataclass
class ExternalClassificationResult:
    candidates: list = field(default_factory=list)
    recommendation: Any = None
    validation_report: Any = None
    decision_report: Any = None
    traversal_report: Any = None
    traversal_history: list[dict[str, Any]] = field(default_factory=list)
    llm_response_text: str = ""
    llm_model: str = ""
    prompt_text: str = ""
    citations: list[dict] = field(default_factory=list)
    semantic_retrieval_status: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class _Stage1ReviewRound:
    candidates: list[Any]
    evidencePackage: Any = None
    validationReport: Any = None
    decisionReport: Any = None
    traversalReport: Any = None
    responseText: str = ""
    modelName: str = ""
    promptText: str = ""
    error: str | None = None


def _BuildCandidateCitations(candidates: Sequence[Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for candidate in candidates:
        citations.append({
            "source_table": "cn_table",
            "source_id": candidate.hs8,
            "snippet": (getattr(candidate, "hs8Description", "") or "")[:120],
            "reason": (
                "Stage 1 shortlist via ASAPExpress CnCandidateRetriever "
                "with retrieval sources: {0}.".format(
                    ", ".join(
                        getattr(candidate, "retrievalSources", [])
                        or ["heuristic"]
                    )
                )
            ),
        })
    return citations


def _ReadField(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            value = obj.get(name)
            if value is not None:
                return value
        return default
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _ReadTextList(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        str(item).strip()
        for item in value[:limit]
        if str(item).strip()
    ]


def _BuildCandidateTraceSnapshot(candidate: Any, rank: int) -> dict[str, Any]:
    hs8 = _candidate_code(candidate, "hs8", "hs8Code")
    codeHierarchy = _ReadField(
        candidate,
        "codeHierarchy",
        "code_hierarchy",
        default={},
    )
    scoreBreakdown = _ReadField(
        candidate,
        "scoreBreakdown",
        "score_breakdown",
        default={},
    )
    snapshot = {
        "rank": rank,
        "hs8": hs8,
        "score": _ReadField(candidate, "score", default=0.0),
        "matchedTerms": _ReadTextList(
            _ReadField(candidate, "matchedTerms", "matched_terms", default=[]),
            limit=12,
        ),
        "retrievalSources": _ReadTextList(
            _ReadField(
                candidate,
                "retrievalSources",
                "retrieval_sources",
                default=[],
            ),
            limit=4,
        ),
        "codeHierarchy": codeHierarchy if isinstance(codeHierarchy, dict) else {},
        "scoreBreakdown": (
            scoreBreakdown
            if isinstance(scoreBreakdown, dict)
            else {}
        ),
        "hardConditions": _ReadField(
            candidate,
            "hardConditions",
            "hard_conditions",
            default="",
        ),
        "hardConditionStatus": _ReadField(
            candidate,
            "hardConditionStatus",
            "hard_condition_status",
            default="not_applicable",
        ),
        "hardConditionEvidence": _ReadTextList(
            _ReadField(
                candidate,
                "hardConditionEvidence",
                "hard_condition_evidence",
                default=[],
            ),
            limit=8,
        ),
    }
    return {
        key: value
        for key, value in snapshot.items()
        if value is not None and value != "" and value != []
    }


def _BuildTraversalHistoryEntry(
    *,
    roundNumber: int,
    phase: str,
    candidates: Sequence[Any],
    traversalReport: Any = None,
    decisionReport: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    entry = {
        "round": roundNumber,
        "phase": phase,
        "candidate_hs8_codes": [
            code
            for code in (_candidate_code(candidate, "hs8") for candidate in candidates)
            if code
        ],
        "candidate_scope": [
            _BuildCandidateTraceSnapshot(candidate, rank)
            for rank, candidate in enumerate(candidates, start=1)
        ],
        "decision_status": _ReadField(
            traversalReport,
            "decisionStatus",
            "decision_status",
            default=_ReadField(
                decisionReport,
                "decisionStatus",
                "decision_status",
                default="unknown",
            ),
        ),
        "traversal_status": _ReadField(
            traversalReport,
            "traversalStatus",
            "traversal_status",
            default="unknown",
        ),
        "next_action": _ReadField(
            traversalReport,
            "nextAction",
            "next_action",
            default="",
        ),
        "retained_candidate_hs8_codes": list(
            _ReadField(
                traversalReport,
                "retainedCandidateHs8Codes",
                "retained_candidate_hs8_codes",
                default=[],
            )
            or []
        ),
        "rejected_candidate_hs8_codes": list(
            _ReadField(
                traversalReport,
                "rejectedCandidateHs8Codes",
                "rejected_candidate_hs8_codes",
                default=[],
            )
            or []
        ),
        "backtracking_recommended": bool(
            _ReadField(
                traversalReport,
                "backtrackingRecommended",
                "backtracking_recommended",
                default=False,
            )
        ),
        "backtracking_target_level": _ReadField(
            traversalReport,
            "backtrackingTargetLevel",
            "backtracking_target_level",
            default=None,
        ),
        "backtracking_reason": _ReadField(
            traversalReport,
            "backtrackingReason",
            "backtracking_reason",
            default=None,
        ),
        "error": error,
    }
    return {
        key: value
        for key, value in entry.items()
        if value is not None and value != ""
    }


def _RunStage1ReviewRound(
    productInput: ProductClassificationInput,
    candidates: Sequence[Any],
    adapter: Any,
) -> _Stage1ReviewRound:
    contextBuilder = OntologyContextBuilder(ASAP_ONTOLOGY_ROOT)
    packagedContext = contextBuilder.BuildContext(
        productInput.BuildSearchText(),
        topK=8,
    )
    evidenceBuilder = Stage1EvidencePackageBuilder(
        ASAP_ONTOLOGY_ROOT,
        ASAP_PROJECT_ROOT,
    )
    evidencePackage = evidenceBuilder.Build(
        productInput,
        candidates,
        packagedContext,
    )

    request = Stage1RequestBuilder().BuildRequest(
        productInput,
        candidates,
        packagedContext,
        evidencePackage=evidencePackage,
    )
    request = _copy_with_clamped_max_tokens(request, LLM_MAX_TOKENS)
    request = _harden_stage1_request(request, productInput, candidates)
    request = _build_compact_decision_request(request, productInput, candidates)
    request = _copy_with_clamped_max_tokens(request, 768)
    promptText = (
        (request.systemPrompt or "")
        + "\n---\n"
        + (request.userPrompt or "")
    )

    try:
        response = adapter.Generate(request)
    except Exception as exception:  # noqa: BLE001
        return _Stage1ReviewRound(
            candidates=list(candidates),
            evidencePackage=evidencePackage,
            promptText=promptText,
            error=f"llm_error: {exception}",
        )

    responseText = getattr(response, "generatedText", "") or ""
    compactDecision = _extract_compact_decision(responseText, candidates)
    if compactDecision is not None:
        compactDecision = _apply_domain_selection_guard(
            compactDecision,
            productInput,
            candidates,
        )
        responseText = _expand_compact_decision_to_stage1_json(
            compactDecision,
            productInput,
            candidates,
        )
        response = _copy_response_with_text(response, responseText)
    modelName = (
        getattr(response, "modelName", None)
        or getattr(response, "model", None)
        or ""
    )

    validator = Stage1ResponseValidator()
    validationReport = validator.ValidateResponse(
        response,
        productInput,
        candidates,
        evidencePackage=evidencePackage,
    )
    if not validationReport.isValid:
        try:
            repairRequest = _copy_with_clamped_max_tokens(
                _build_repair_request(
                    request,
                    productInput,
                    candidates,
                    responseText,
                    validationReport,
                ),
                LLM_MAX_TOKENS,
            )
            repairResponse = adapter.Generate(repairRequest)
            repairValidation = validator.ValidateResponse(
                repairResponse,
                productInput,
                candidates,
                evidencePackage=evidencePackage,
            )
            if repairValidation.isValid:
                response = repairResponse
                responseText = getattr(response, "generatedText", "") or ""
                validationReport = repairValidation
                modelName = (
                    getattr(response, "modelName", None)
                    or getattr(response, "model", None)
                    or modelName
                )
        except Exception:
            pass

    decisionPolicy = Stage1DecisionPolicy()
    decisionReport = decisionPolicy.BuildDecision(
        validationReport,
        candidates,
    )
    traversalReport = Stage1TraversalController(
        decisionPolicy=decisionPolicy,
    ).BuildFromDecision(decisionReport, candidates)
    return _Stage1ReviewRound(
        candidates=list(candidates),
        evidencePackage=evidencePackage,
        validationReport=validationReport,
        decisionReport=decisionReport,
        traversalReport=traversalReport,
        responseText=responseText,
        modelName=str(modelName),
        promptText=promptText,
    )


# ---------------------------------------------------------------------------
# RuntimeAdapter (bridge) — env / .appconfig backed
# ---------------------------------------------------------------------------
def build_runtime_adapter():
    """Build a RuntimeAdapter from ASAP/.env or fallback to default config."""
    try:
        env_path = ASAP_ENV_FILE if ASAP_ENV_FILE.exists() else None
        runtimeConfig = BuildLlmRuntimeConfigFromEnv(envFilePath=env_path)
    except Exception:
        runtimeConfig = BuildDefaultLlmRuntimeConfig()
    dependencyStatus = ProbeRuntimeDependency(runtimeConfig)
    return BuildRuntimeAdapter(runtimeConfig, dependencyStatus)


def build_semantic_candidate_index(
    retriever: CnCandidateRetriever,
) -> tuple[CnSemanticCandidateIndex | None, dict[str, Any]]:
    global SEMANTIC_CANDIDATE_INDEX
    global SEMANTIC_CANDIDATE_INDEX_STATUS

    if SEMANTIC_CANDIDATE_INDEX is not None:
        return SEMANTIC_CANDIDATE_INDEX, {
            "status": "ready",
            "chunk_count": SEMANTIC_CANDIDATE_INDEX.chunkCount,
        }
    if SEMANTIC_CANDIDATE_INDEX_STATUS is not None:
        return None, dict(SEMANTIC_CANDIDATE_INDEX_STATUS)

    if not APP_CONFIG.classification.use_semantic_candidate_retrieval:
        SEMANTIC_CANDIDATE_INDEX_STATUS = {
            "status": "disabled",
            "reason": "semantic candidate retrieval is disabled by appconfig",
        }
        return None, dict(SEMANTIC_CANDIDATE_INDEX_STATUS)

    runtimeConfig = BuildTextEmbeddingRuntimeConfig(APP_CONFIG.embedding)
    if not runtimeConfig.enabled:
        SEMANTIC_CANDIDATE_INDEX_STATUS = {
            "status": "disabled",
            "reason": "embedding runtime is disabled by appconfig",
            "provider": runtimeConfig.provider.value,
            "model": runtimeConfig.modelName,
        }
        return None, dict(SEMANTIC_CANDIDATE_INDEX_STATUS)

    dependencyStatus = ProbeTextEmbeddingDependency(runtimeConfig)
    if not dependencyStatus.isAvailable:
        SEMANTIC_CANDIDATE_INDEX_STATUS = {
            "status": "unavailable",
            "reason": dependencyStatus.message,
            "provider": dependencyStatus.provider.value,
            "model": runtimeConfig.modelName,
            "limitations": list(dependencyStatus.limitations),
        }
        return None, dict(SEMANTIC_CANDIDATE_INDEX_STATUS)

    try:
        embeddingAdapter = BuildTextEmbeddingAdapter(
            runtimeConfig,
            dependencyStatus=dependencyStatus,
        )
        if embeddingAdapter is None:
            SEMANTIC_CANDIDATE_INDEX_STATUS = {
                "status": "disabled",
                "reason": "embedding adapter was not created",
                "provider": runtimeConfig.provider.value,
                "model": runtimeConfig.modelName,
            }
            return None, dict(SEMANTIC_CANDIDATE_INDEX_STATUS)

        semanticIndex = CnSemanticCandidateIndex(embeddingAdapter)
        semanticIndex.Build(retriever.LoadRowsByDomainScope())
    except (
        TextEmbeddingAdapterBuildError,
        TextEmbeddingGenerationError,
        ValueError,
    ) as exception:
        SEMANTIC_CANDIDATE_INDEX_STATUS = {
            "status": "failed",
            "reason": str(exception),
            "provider": runtimeConfig.provider.value,
            "model": runtimeConfig.modelName,
        }
        return None, dict(SEMANTIC_CANDIDATE_INDEX_STATUS)

    SEMANTIC_CANDIDATE_INDEX = semanticIndex
    return SEMANTIC_CANDIDATE_INDEX, {
        "status": "ready",
        "provider": runtimeConfig.provider.value,
        "model": runtimeConfig.modelName,
        "chunk_count": semanticIndex.chunkCount,
    }


# ---------------------------------------------------------------------------
# PES → ProductClassificationInput
# ---------------------------------------------------------------------------
def pes_to_input(pes: dict, *, domain_scope: str = "food_16_21") -> ProductClassificationInput:
    """Map our Blackboard ProductEvidenceState to ASAPExpress input."""
    obs = pes.get("observed_facts") or {}

    ocr_chunks = obs.get("ocr_text") or []
    if isinstance(ocr_chunks, list):
        ocr_text = "\n".join(str(t) for t in ocr_chunks if t)
    else:
        ocr_text = str(ocr_chunks)
    composition = (
        obs.get("classification_input_fact_texts")
        or obs.get("composition")
        or []
    )
    if not isinstance(composition, list):
        composition = [str(composition)] if str(composition).strip() else []
    classification_input_facts = (
        obs.get("classification_input_product_facts")
        or []
    )
    if not isinstance(classification_input_facts, list):
        classification_input_facts = []
    unresolved_product_facts = obs.get("unresolved_product_facts") or []
    if not isinstance(unresolved_product_facts, list):
        unresolved_product_facts = []
    product_fact_conflicts = obs.get("product_fact_conflicts") or []
    if not isinstance(product_fact_conflicts, list):
        product_fact_conflicts = [product_fact_conflicts]

    return ProductClassificationInput(
        productName=obs.get("product_name") or "",
        shortDescription=obs.get("description") or "",
        productDomain=domain_scope,
        domainScopes=[domain_scope],
        normalizedOcrFactTexts=[str(t) for t in composition if str(t).strip()],
        structuredProductFacts=[
            dict(item) for item in classification_input_facts if isinstance(item, dict)
        ],
        unresolvedProductFacts=[
            dict(item) for item in unresolved_product_facts if isinstance(item, dict)
        ],
        productFactConflicts=product_fact_conflicts,
        ocrText=ocr_text,
    )


# ---------------------------------------------------------------------------
# Main entry — 7-step orchestration
# ---------------------------------------------------------------------------
def run_external_classifier(
    pes: dict,
    *,
    domain_scope: str = "food_16_21",
    runtime_adapter=None,
    top_k_candidates: int = 5,
) -> ExternalClassificationResult:
    productInput = pes_to_input(pes, domain_scope=domain_scope)
    candidateLimit = max(1, min(int(top_k_candidates), 5))

    # 2. Retrieval
    classificationConfig = APP_CONFIG.classification
    retriever = CnCandidateRetriever(
        ASAP_ONTOLOGY_ROOT,
        ASAP_PROJECT_ROOT,
        beamConfig=HierarchyBeamConfig(
            hs2PerParent=classificationConfig.beam_hs2_per_parent,
            hs4PerParent=classificationConfig.beam_hs4_per_parent,
            hs6PerParent=classificationConfig.beam_hs6_per_parent,
            hs2GlobalLimit=classificationConfig.beam_hs2_global_limit,
            hs4GlobalLimit=classificationConfig.beam_hs4_global_limit,
            hs6GlobalLimit=classificationConfig.beam_hs6_global_limit,
            semanticSlotsPerParent=(
                classificationConfig.beam_semantic_slots_per_parent
            ),
        ),
    )
    semanticIndex, semanticStatus = build_semantic_candidate_index(retriever)
    if semanticIndex is None:
        candidates = retriever.FindCandidates(productInput, topK=candidateLimit)
    else:
        candidates = retriever.FindCandidatesWithSemanticIndex(
            productInput,
            semanticIndex,
            heuristicTopK=candidateLimit,
            semanticTopK=APP_CONFIG.classification.semantic_candidate_top_k,
            finalCandidateLimit=(
                min(APP_CONFIG.classification.hybrid_candidate_limit, candidateLimit)
                if APP_CONFIG.classification.hybrid_candidate_limit
                else candidateLimit
            ),
            minSemanticScore=APP_CONFIG.classification.semantic_min_score,
        )
    candidates = list(candidates)[:candidateLimit]
    if not candidates:
        return ExternalClassificationResult(
            candidates=[],
            semantic_retrieval_status=semanticStatus,
            error="no_candidates_from_retriever",
        )

    try:
        adapter = runtime_adapter or build_runtime_adapter()
    except Exception as exception:  # noqa: BLE001
        return ExternalClassificationResult(
            candidates=list(candidates),
            citations=_BuildCandidateCitations(candidates),
            semantic_retrieval_status=semanticStatus,
            error=f"llm_adapter_error: {exception}",
        )

    reviewRound = _RunStage1ReviewRound(
        productInput,
        candidates,
        adapter,
    )
    if reviewRound.error is not None:
        return ExternalClassificationResult(
            candidates=reviewRound.candidates,
            citations=_BuildCandidateCitations(reviewRound.candidates),
            prompt_text=reviewRound.promptText[:2000],
            semantic_retrieval_status=semanticStatus,
            error=reviewRound.error,
        )

    traversalHistory = [
        _BuildTraversalHistoryEntry(
            roundNumber=1,
            phase="initial_review",
            candidates=reviewRound.candidates,
            traversalReport=reviewRound.traversalReport,
            decisionReport=reviewRound.decisionReport,
        )
    ]
    traversalController = Stage1TraversalController()
    if (
        reviewRound.traversalReport.nextAction
        == "backtrack_candidate_scope"
        and classificationConfig.backtracking_max_retry_count > 0
    ):
        backtrackingCandidates = traversalController.BuildBacktrackingCandidates(
            productInput=productInput,
            currentCandidates=reviewRound.candidates,
            decisionReport=reviewRound.decisionReport,
            candidateRetriever=retriever,
            topK=candidateLimit,
            visitedHs8Codes=[
                candidate.hs8 for candidate in reviewRound.candidates
            ],
            completedRetryCount=0,
            maxRetryCount=classificationConfig.backtracking_max_retry_count,
            semanticIndex=semanticIndex,
            semanticTopK=classificationConfig.semantic_candidate_top_k,
            minSemanticScore=classificationConfig.semantic_min_score,
        )
        if not backtrackingCandidates:
            traversalHistory.append(
                _BuildTraversalHistoryEntry(
                    roundNumber=2,
                    phase="backtracking_scope_exhausted",
                    candidates=[],
                    traversalReport=None,
                    decisionReport=reviewRound.decisionReport,
                    error="backtracking_scope_exhausted",
                )
            )
            return ExternalClassificationResult(
                candidates=reviewRound.candidates,
                validation_report=reviewRound.validationReport,
                decision_report=reviewRound.decisionReport,
                traversal_report=reviewRound.traversalReport,
                traversal_history=traversalHistory,
                llm_response_text=reviewRound.responseText,
                llm_model=reviewRound.modelName,
                prompt_text=reviewRound.promptText[:2000],
                citations=_BuildCandidateCitations(reviewRound.candidates),
                semantic_retrieval_status=semanticStatus,
                error="backtracking_scope_exhausted",
            )
        reviewRound = _RunStage1ReviewRound(
            productInput,
            list(backtrackingCandidates)[:candidateLimit],
            adapter,
        )
        if reviewRound.error is not None:
            error = "backtracking_{0}".format(reviewRound.error)
            traversalHistory.append(
                _BuildTraversalHistoryEntry(
                    roundNumber=2,
                    phase="backtracking_retry_error",
                    candidates=reviewRound.candidates,
                    traversalReport=reviewRound.traversalReport,
                    decisionReport=reviewRound.decisionReport,
                    error=error,
                )
            )
            return ExternalClassificationResult(
                candidates=reviewRound.candidates,
                citations=_BuildCandidateCitations(reviewRound.candidates),
                traversal_history=traversalHistory,
                prompt_text=reviewRound.promptText[:2000],
                semantic_retrieval_status=semanticStatus,
                error=error,
            )
        traversalHistory.append(
            _BuildTraversalHistoryEntry(
                roundNumber=2,
                phase="backtracking_retry",
                candidates=reviewRound.candidates,
                traversalReport=reviewRound.traversalReport,
                decisionReport=reviewRound.decisionReport,
            )
        )

    recommendation = Stage1RecommendationReportBuilder().Build(
        productInput,
        reviewRound.candidates,
        reviewRound.validationReport,
        reviewRound.decisionReport,
        reviewRound.traversalReport,
        evidencePackage=reviewRound.evidencePackage,
    )

    return ExternalClassificationResult(
        candidates=reviewRound.candidates,
        recommendation=recommendation,
        validation_report=reviewRound.validationReport,
        decision_report=reviewRound.decisionReport,
        traversal_report=reviewRound.traversalReport,
        traversal_history=traversalHistory,
        llm_response_text=reviewRound.responseText,
        llm_model=reviewRound.modelName,
        prompt_text=reviewRound.promptText[:2000],
        citations=_BuildCandidateCitations(reviewRound.candidates),
        semantic_retrieval_status=semanticStatus,
    )
