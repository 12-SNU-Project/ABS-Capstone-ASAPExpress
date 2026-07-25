"""Frontend-facing pipeline API contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bussiness_logic.utils.json_types import JsonObject


RunStatus = Literal["queued", "running", "completed", "failed"]
IngredientRole = Literal["primary", "secondary"]
IntendedUse = Literal[
    "human consumption",
    "further processing",
    "animal feed",
    "non-food use",
]

ISO_ALPHA2_CODES = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ
BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY
HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP
KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY
MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR
PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN
SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW
TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())


class ApiContractModel(BaseModel):
    """Base model for JSON responses exposed by `/api/*` routes."""

    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="forbid")

    def ToDict(self) -> JsonObject:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class ApiErrorResponse(ApiContractModel):
    error: str
    message: str
    field: str | None = None
    hint: str | None = None
    jobId: str | None = Field(default=None, alias="job_id")
    retryAfterSeconds: int | None = Field(default=None, alias="retry_after_seconds")


class IngredientInputPayload(ApiContractModel):
    role: IngredientRole
    name: str = Field(min_length=1, max_length=100)
    percentage: float = Field(gt=0, le=100)

    @field_validator("name")
    @classmethod
    def ValidateName(cls, value: str) -> str:
        normalizedValue = " ".join(value.split())
        if not re.search(r"[A-Za-z가-힣]", normalizedValue):
            raise ValueError("Ingredient name must contain a Korean or Latin letter.")
        return normalizedValue


class InputFactsPayload(ApiContractModel):
    ingredients: list[IngredientInputPayload] = Field(default_factory=list, max_length=20)
    intendedUse: IntendedUse | None = Field(default=None, alias="intended_use")
    originCountry: str = Field(default="", alias="origin_country", max_length=2)

    @field_validator("originCountry")
    @classmethod
    def ValidateOriginCountry(cls, value: str) -> str:
        normalizedValue = value.strip().upper()
        if normalizedValue and normalizedValue not in ISO_ALPHA2_CODES:
            raise ValueError("Origin country must be a valid ISO alpha-2 code.")
        return normalizedValue

    @model_validator(mode="after")
    def ValidateIngredients(self) -> "InputFactsPayload":
        if not self.ingredients:
            return self
        primaryCount = sum(item.role == "primary" for item in self.ingredients)
        if primaryCount != 1:
            raise ValueError("Exactly one primary ingredient is required.")
        normalizedNames = [item.name.casefold() for item in self.ingredients]
        if len(normalizedNames) != len(set(normalizedNames)):
            raise ValueError("Ingredient names must not be duplicated.")
        if sum(item.percentage for item in self.ingredients) > 100:
            raise ValueError("Ingredient percentages must total 100 or less.")
        return self


class RunCreateRequestPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    query: str = ""
    productName: str = Field(default="", alias="product_name")
    description: str = ""
    url: str = ""
    kurlyUrl: str = Field(default="", alias="kurly_url")
    facts: JsonObject = Field(default_factory=dict)
    inputFacts: InputFactsPayload | None = Field(default=None, alias="input_facts")


class RunCreateAcceptedResponse(ApiContractModel):
    jobId: str = Field(alias="job_id")
    status: RunStatus
    reused: bool
    eventsUrl: str = Field(alias="events_url")
    resultUrl: str = Field(alias="result_url")


class QuestionAnswerPayload(ApiContractModel):
    userQuestionId: str = Field(alias="user_question_id", min_length=1)
    answer: Literal["yes", "no", "unknown"]


class QuestionAnswersRequestPayload(ApiContractModel):
    answers: list[QuestionAnswerPayload] = Field(min_length=1, max_length=8)


class RunRequestView(ApiContractModel):
    query: str = ""
    facts: JsonObject = Field(default_factory=dict)


class PageProductFactsView(ApiContractModel):
    productName: str = Field(default="", alias="product_name")
    description: str = ""
    url: str = ""
    sourceUrls: list[str] = Field(default_factory=list, alias="source_urls")
    ingredients: list[JsonObject] = Field(default_factory=list)
    intendedUse: str = Field(default="", alias="intended_use")
    originCountry: str = Field(default="", alias="origin_country")


class ReconstructionStatusView(ApiContractModel):
    mode: str = ""
    usedLlmReconstruction: bool = Field(
        default=False,
        alias="used_llm_reconstruction",
    )
    fallbackReason: str = Field(default="", alias="fallback_reason")
    error: str = ""
    detailTableCount: int = Field(default=0, alias="detail_table_count")
    classificationFactCount: int = Field(
        default=0,
        alias="classification_fact_count",
    )
    classificationTextLineCount: int = Field(
        default=0,
        alias="classification_text_line_count",
    )


class InputProcessingView(ApiContractModel):
    pageProductFacts: PageProductFactsView = Field(alias="page_product_facts")
    detailEvidenceRows: list[JsonObject] = Field(
        default_factory=list,
        alias="detail_evidence_rows",
    )
    reconstructedDetailTables: list[JsonObject] = Field(
        default_factory=list,
        alias="reconstructed_detail_tables",
    )
    reconstructedProductFacts: list[JsonObject] = Field(
        default_factory=list,
        alias="reconstructed_product_facts",
    )
    reconstructedFactTextLines: list[str] = Field(
        default_factory=list,
        alias="reconstructed_fact_texts",
    )
    unresolvedProductFacts: list[JsonObject] = Field(
        default_factory=list,
        alias="unresolved_product_facts",
    )
    reconstructionEvidenceTraces: list[JsonObject] = Field(
        default_factory=list,
        alias="reconstruction_evidence_traces",
    )
    missingFactReasons: list[JsonObject] = Field(
        default_factory=list,
        alias="missing_fact_reasons",
    )
    productFactConflicts: list[str] = Field(
        default_factory=list,
        alias="product_fact_conflicts",
    )
    warnings: list[str] = Field(default_factory=list)
    evidenceSourceLabels: dict[str, str] = Field(
        default_factory=dict,
        alias="evidence_source_labels",
    )
    reconstructionStatus: ReconstructionStatusView = Field(
        alias="reconstruction_status",
    )


class CandidateCodeView(ApiContractModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="allow")

    candidateId: str | None = Field(default=None, alias="candidate_id")
    hs6: str | None = None
    cn8: str | None = None
    taric10: str | None = None
    taric10BranchCandidates: list[JsonObject] = Field(
        default_factory=list,
        alias="taric10_branch_candidates",
    )
    taric10ResolutionMode: str | None = Field(
        default=None,
        alias="taric10_resolution_mode",
    )
    taric10IsRecommended: bool | None = Field(
        default=None,
        alias="taric10_is_recommended",
    )
    taric10BranchCount: int | None = Field(
        default=None,
        alias="taric10_branch_count",
    )
    rank: int | None = None
    status: str | None = None
    candidateSource: str | None = Field(default=None, alias="candidate_source")
    llmRecommended: bool | None = Field(default=None, alias="llm_recommended")
    candidateStaticTree: JsonObject | None = Field(
        default=None,
        alias="candidate_static_tree",
    )
    hardConditions: str | None = Field(default=None, alias="hard_conditions")
    hardConditionStatus: str | None = Field(
        default=None,
        alias="hard_condition_status",
    )
    hardConditionEvidence: list[str] | None = Field(
        default=None,
        alias="hard_condition_evidence",
    )
    classificationBasis: list[str] = Field(
        default_factory=list,
        alias="classification_basis",
    )
    classificationCitations: list[JsonObject] = Field(
        default_factory=list,
        alias="classification_citations",
    )
    requiredFacts: list[str] = Field(default_factory=list, alias="required_facts")
    unknowns: list[str] = Field(default_factory=list)
    similarEbtiCases: list[JsonObject] = Field(
        default_factory=list,
        alias="similar_ebti_cases",
    )

    @model_validator(mode="before")
    @classmethod
    def DropLegacyTaricReasonFields(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        cleanedValue = dict(value)
        cleanedValue.pop("selected_taric10_reason", None)
        cleanedValue.pop("primary_taric10_reason", None)
        return cleanedValue


class ClassificationPathView(ApiContractModel):
    hs2: str | None = None
    hs4: str | None = None
    hs6: str | None = None
    cn8: str | None = None
    levelScores: dict[str, float] = Field(
        default_factory=dict,
        alias="level_scores",
    )
    source: str | None = None


class ClassificationTraceView(ApiContractModel):
    mode: str | None = None
    stages: list[JsonObject] = Field(default_factory=list)
    validator: JsonObject | None = None
    backtrackingRecommended: bool | None = Field(
        default=None,
        alias="backtracking_recommended",
    )


class ClassificationCandidateSetView(ApiContractModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="allow")

    candidateSetId: str | None = Field(default=None, alias="candidate_set_id")
    productId: str | None = Field(default=None, alias="product_id")
    classificationStatus: str | None = Field(
        default=None,
        alias="classification_status",
    )
    failureReason: str | None = Field(default=None, alias="failure_reason")
    shortlistedCandidates: list[JsonObject] = Field(
        default_factory=list,
        alias="shortlisted_candidates",
    )
    candidates: list[CandidateCodeView] = Field(default_factory=list)
    selectedPath: ClassificationPathView | None = Field(
        default=None,
        alias="selected_path",
    )
    classificationTrace: ClassificationTraceView | None = Field(
        default=None,
        alias="classification_trace",
    )
    btiSummons: list[JsonObject] = Field(
        default_factory=list,
        alias="bti_summons",
    )


class ProductUnderstandingView(ApiContractModel):
    understandingId: str | None = Field(default=None, alias="understanding_id")
    productId: str | None = Field(default=None, alias="product_id")
    productName: str | None = Field(default=None, alias="product_name")
    shortDescription: str = Field(default="", alias="short_description")
    routingTerms: list[str] = Field(default_factory=list, alias="routing_terms")
    blockedRoutingTerms: list[str] = Field(
        default_factory=list,
        alias="blocked_routing_terms",
    )
    excludedFromRoutingTerms: list[str] = Field(
        default_factory=list,
        alias="excluded_from_routing_terms",
    )
    unknowns: list[str] = Field(default_factory=list)
    reconstructedFactTextCount: int = Field(
        default=0,
        alias="reconstructed_fact_text_count",
    )
    reconstructedProductFactCount: int = Field(
        default=0,
        alias="reconstructed_product_fact_count",
    )
    identityHints: JsonObject = Field(default_factory=dict, alias="identity_hints")
    distilledIdentity: JsonObject = Field(
        default_factory=dict,
        alias="distilled_identity",
    )
    compositionFacts: JsonObject = Field(
        default_factory=dict,
        alias="composition_facts",
    )
    encyclopediaEvidence: JsonObject = Field(
        default_factory=dict,
        alias="encyclopedia_evidence",
    )
    coiEvidence: JsonObject = Field(default_factory=dict, alias="coi_evidence")


class RoutingView(ApiContractModel):
    allowedHs2: list[str] = Field(default_factory=list, alias="allowed_hs2")
    blockedHs2: list[str] = Field(default_factory=list, alias="blocked_hs2")
    enforceHs2Boundary: bool | None = Field(
        default=None,
        alias="enforce_hs2_boundary",
    )
    fallbackAllowed: bool | None = Field(default=None, alias="fallback_allowed")
    domainScopes: list[str] = Field(default_factory=list, alias="domain_scopes")
    preGateDomains: list[str] = Field(default_factory=list, alias="pre_gate_domains")
    missingFacts: list[str] = Field(default_factory=list, alias="missing_facts")
    routingBasis: JsonObject = Field(default_factory=dict, alias="routing_basis")
    candidateChapterDetails: list[JsonObject] = Field(
        default_factory=list,
        alias="candidate_chapter_details",
    )


class DocumentPackageView(ApiContractModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="allow")

    documentPackageId: str | None = Field(default=None, alias="document_package_id")
    taric10: str | None = None
    cn8: str | None = None

    @model_validator(mode="before")
    @classmethod
    def RejectRawDocumentPackage(cls, value: object) -> object:
        if isinstance(value, Mapping) and "raw_document_package" in value:
            raise ValueError("raw_document_package is not part of the public API.")
        return value


class DocumentPackageSummaryView(ApiContractModel):
    documentPackageId: str | None = Field(default=None, alias="document_package_id")
    candidateId: str | None = Field(default=None, alias="candidate_id")
    taric10: str | None = None
    cn8: str | None = None
    taric10BranchIndex: int | None = Field(
        default=None,
        alias="taric10_branch_index",
    )
    taric10BranchCount: int | None = Field(
        default=None,
        alias="taric10_branch_count",
    )
    taric10ResolutionMode: str | None = Field(
        default=None,
        alias="taric10_resolution_mode",
    )
    taric10IsRecommended: bool | None = Field(
        default=None,
        alias="taric10_is_recommended",
    )
    requiredDocumentCount: int = Field(
        default=0,
        alias="required_document_count",
    )
    summary: JsonObject = Field(default_factory=dict)
    checklistSummary: JsonObject = Field(
        default_factory=dict,
        alias="checklist_summary",
    )
    productFacts: JsonObject = Field(default_factory=dict, alias="product_facts")
    missingFacts: list[str] = Field(default_factory=list, alias="missing_facts")
    backtrackingSignals: list[JsonObject] = Field(
        default_factory=list,
        alias="backtracking_signals",
    )


class DocumentPackageCollectionResponse(ApiContractModel):
    jobId: str = Field(alias="job_id")
    runId: str | None = Field(default=None, alias="run_id")
    total: int
    packages: list[DocumentPackageSummaryView] = Field(default_factory=list)


class DocumentPackageDetailResponse(ApiContractModel):
    jobId: str = Field(alias="job_id")
    runId: str | None = Field(default=None, alias="run_id")
    documentPackage: DocumentPackageView = Field(alias="document_package")


class PipelineEventPayload(ApiContractModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="allow")

    stage: str = ""
    status: str = ""
    message: str = ""
    ts: str | None = None
    partialResult: JsonObject | None = Field(
        default=None,
        alias="partial_result",
    )
    collectedInputSummary: JsonObject | None = Field(
        default=None,
        alias="collected_input_summary",
    )


class RunSnapshotResponse(ApiContractModel):
    jobId: str = Field(alias="job_id")
    jobStatus: RunStatus = Field(alias="job_status")
    events: list[PipelineEventPayload] = Field(default_factory=list)
    request: RunRequestView
    runId: str | None = Field(default=None, alias="run_id")
    runDir: str | None = Field(default=None, alias="run_dir")
    auditRef: JsonObject | None = Field(default=None, alias="audit_ref")
    inputProcessingSummary: JsonObject | None = Field(
        default=None,
        alias="input_processing_summary",
    )
    inputProcessingView: InputProcessingView | None = Field(
        default=None,
        alias="input_processing_view",
    )
    productUnderstandingView: ProductUnderstandingView | None = Field(
        default=None,
        alias="product_understanding_view",
    )
    routingView: RoutingView | None = Field(
        default=None,
        alias="routing_view",
    )
    candidateCodeSet: ClassificationCandidateSetView | None = Field(
        default=None,
        alias="candidate_code_set",
    )
    userQuestions: list[JsonObject] = Field(
        default_factory=list,
        alias="user_questions",
    )
    documentPackage: DocumentPackageSummaryView | None = Field(
        default=None,
        alias="document_package",
    )
    documentPackages: list[DocumentPackageSummaryView] = Field(
        default_factory=list,
        alias="document_packages",
    )
    decision: JsonObject | None = None
    componentResults: list[JsonObject] | None = Field(
        default=None,
        alias="component_results",
    )
    error: str | None = None


class RunCompleteSsePayload(ApiContractModel):
    runId: str = Field(alias="run_id")
    status: Literal["completed", "failed"]


class RunNotFoundSsePayload(ApiContractModel):
    error: Literal["run_not_found"] = "run_not_found"
    message: str
    runId: str = Field(alias="run_id")
