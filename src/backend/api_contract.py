"""Frontend-facing pipeline API contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bussiness_logic.utils.json_types import JsonObject


RunStatus = Literal["queued", "running", "completed", "failed"]


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


class RunCreateRequestPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    query: str = ""
    productName: str = Field(default="", alias="product_name")
    description: str = ""
    url: str = ""
    kurlyUrl: str = Field(default="", alias="kurly_url")
    facts: JsonObject = Field(default_factory=dict)


class RunCreateAcceptedResponse(ApiContractModel):
    jobId: str = Field(alias="job_id")
    status: RunStatus
    reused: bool
    eventsUrl: str = Field(alias="events_url")
    resultUrl: str = Field(alias="result_url")


class RunRequestView(ApiContractModel):
    query: str = ""
    facts: JsonObject = Field(default_factory=dict)


class PageProductFactsView(ApiContractModel):
    productName: str = Field(default="", alias="product_name")
    description: str = ""
    url: str = ""
    sourceUrls: list[str] = Field(default_factory=list, alias="source_urls")


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
    productFactConflicts: list[str] = Field(
        default_factory=list,
        alias="product_fact_conflicts",
    )
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

    @model_validator(mode="before")
    @classmethod
    def DropLegacyTaricReasonFields(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        cleanedValue = dict(value)
        cleanedValue.pop("selected_taric10_reason", None)
        cleanedValue.pop("primary_taric10_reason", None)
        return cleanedValue


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


class DocumentPackageCollectionResponse(ApiContractModel):
    jobId: str = Field(alias="job_id")
    runId: str | None = Field(default=None, alias="run_id")
    total: int
    packages: list[DocumentPackageView] = Field(default_factory=list)


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
    candidateCodeSet: ClassificationCandidateSetView | None = Field(
        default=None,
        alias="candidate_code_set",
    )
    documentPackage: DocumentPackageView | None = Field(
        default=None,
        alias="document_package",
    )
    documentPackages: list[DocumentPackageView] = Field(
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
