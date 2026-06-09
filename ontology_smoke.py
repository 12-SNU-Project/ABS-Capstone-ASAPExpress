"""Ontology context/request builder runtime smoke.

이 파일은 ontology 관련 smoke를 단계별로 누적하는 단일 진입점이다.
새 smoke 단계가 필요하면 별도 파일을 만들지 말고 이 runner에 단계를 추가한다.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
)


PROJECT_ROOT_PATH = Path(__file__).resolve().parent
SOURCE_ROOT_PATH = PROJECT_ROOT_PATH / "src"
if str(SOURCE_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT_PATH))

from eu_export.bridge import (  # noqa: E402
    BuildLlmRuntimeConfigFromEnv,
    BuildRuntimeAdapter,
    BuildTextEmbeddingAdapter,
    BuildTextEmbeddingRuntimeConfig,
    ProbeRuntimeDependency,
    ProbeTextEmbeddingDependency,
    RuntimeAdapterBuildError,
    RuntimeGenerationError,
    TextEmbeddingAdapterBuildError,
    TextEmbeddingGenerationError,
)
from eu_export.app_config import LoadAppConfig  # noqa: E402
from eu_export.ontology import (  # noqa: E402
    CnCandidate,
    CnCandidateRetriever,
    CnSemanticCandidateIndex,
    DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
    LlmRequestBuilder,
    OntologyContextBuilder,
    OntologyGraphValidator,
    OntologyResourceResolver,
    ProductClassificationInput,
    ProductClassificationInputNormalizer,
    Stage1RecommendationReportBuilder,
    Stage1ResponseValidator,
    Stage1ResponseValidationReport,
    Stage1ResponseValidationIssue,
    Stage1RequestBuilder,
    Stage1DecisionPolicy,
    Stage1DecisionReport,
    Stage1EvidencePackage,
    Stage1EvidencePackageBuilder,
    Stage1HumanReviewPackageBuilder,
    Stage1TraversalController,
)
from eu_export.utils import NormalizeWhitespace  # noqa: E402


NO_CN_CANDIDATE_REASON = "no CN candidates found for product input"


class ProductSmokeProductPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_name: Optional[StrictStr] = None
    product_domain: Optional[StrictStr] = None
    short_description: Optional[StrictStr] = None
    brand_name: Optional[StrictStr] = None
    package_type: Optional[StrictStr] = None
    sale_unit: Optional[StrictStr] = None


class ProductSmokeNoticePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    line_count: Optional[StrictInt] = None
    field_count: Optional[StrictInt] = None
    option_count: Optional[StrictInt] = None
    option_names: List[StrictStr] = Field(default_factory=list)
    fields_preview: List[Dict[str, Any]] = Field(default_factory=list)
    options_preview: List[Dict[str, Any]] = Field(default_factory=list)
    requires_ocr_fallback: Optional[StrictBool] = None
    image_reference_detected: Optional[StrictBool] = None


class ProductSmokeOcrPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_detail_image_url_count: Optional[StrictInt] = None
    candidate_image_url_count: Optional[StrictInt] = None
    candidate_image_urls_preview: List[StrictStr] = Field(default_factory=list)
    image_result_count: Optional[StrictInt] = None
    successful_image_count: Optional[StrictInt] = None
    image_artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    combined_text_length: Optional[StrictInt] = None
    combined_text_preview: Optional[StrictStr] = None


class ProductSmokeSummaryPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_page_url: Optional[StrictStr] = None
    parsed_product_page: Optional[Dict[str, Any]] = None
    collection_summary: Optional[Dict[str, Any]] = None
    rendered_page_evidence_summary: Optional[Dict[str, Any]] = None
    ocr_summary: Optional[Dict[str, Any]] = None
    combined_ocr_text: Optional[StrictStr] = None
    steps: Optional[List[Dict[str, Any]]] = None
    pipeline_steps: Optional[List[Dict[str, Any]]] = None
    warnings: List[Any] = Field(default_factory=list)
    errors: List[Any] = Field(default_factory=list)
    status: Dict[str, Any] = Field(default_factory=dict)
    product: Optional[ProductSmokeProductPayload] = None
    notice: Optional[ProductSmokeNoticePayload] = None
    ocr: Optional[ProductSmokeOcrPayload] = None


class OntologySmokeRunner:
    """ontology 문서 로드, 검색 context, LLM request 생성을 확인한다."""

    def __init__(self) -> None:
        appConfig = LoadAppConfig(PROJECT_ROOT_PATH)
        pathConfig = appConfig.paths
        smokeConfig = appConfig.ontology_smoke
        embeddingConfig = appConfig.embedding

        self._ontologyRootPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            pathConfig.ontology_root,
        )
        self._summaryArtifactPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            pathConfig.ontology_smoke_summary_artifact,
        )
        self._humanReviewPackageArtifactPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            pathConfig.ontology_human_review_package_artifact,
        )
        self._productSmokeSummaryArtifactPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            pathConfig.kurly_smoke_summary_artifact,
        )

        self._phaseId = smokeConfig.phase_id
        self._topK = smokeConfig.top_k
        self._maxResultCount = smokeConfig.max_result_count
        self._cnCandidateTopK = smokeConfig.cn_candidate_top_k
        self._maxProductSmokeInputs = smokeConfig.max_product_smoke_inputs
        self._writeSummaryArtifact = smokeConfig.write_summary_artifact
        self._runLlmConnectionSmoke = smokeConfig.run_llm_connection_smoke
        self._textPreviewCharacters = smokeConfig.text_preview_characters
        self._validationIssuePreviewCount = smokeConfig.validation_issue_preview_count
        self._resourceCheckPreviewCount = smokeConfig.resource_check_preview_count
        self._maxValidationFixtureCandidates = (
            smokeConfig.max_validation_fixture_candidates
        )
        self._stage1BacktrackingRetryAttempt = (
            smokeConfig.stage1_backtracking_retry_attempt
        )
        self._embeddingConfig = embeddingConfig
        self._useSemanticCandidateRetrieval = (
            smokeConfig.use_semantic_candidate_retrieval
        )
        self._semanticCandidateTopK = smokeConfig.semantic_candidate_top_k
        self._semanticMinScore = smokeConfig.semantic_min_score
        self._hybridCandidateLimit = smokeConfig.hybrid_candidate_limit
        self._semanticCandidateIndex: Optional[CnSemanticCandidateIndex] = None
        self._semanticCandidateIndexStatus: Optional[Dict[str, Any]] = None
        self._smokeQueries = [
            {
                "name": "stage1_cosmetics_classification",
                "phase_id": self._phaseId,
                "query": (
                    "화장품 HS6 CN8 후보 분류 stage1 classification "
                    "cn_leaf_code_cards classification evidence"
                ),
                "user_prompt": "화장품 제품의 HS6/CN8 후보 분류 기준을 설명해줘.",
            },
            {
                "name": "stage1_food_classification",
                "phase_id": self._phaseId,
                "query": (
                    "식품 HS6 CN8 후보 분류 stage1 classification "
                    "food cn_leaf_code_cards domain scope"
                ),
                "user_prompt": "식품 제품의 HS6/CN8 후보 분류 기준을 설명해줘.",
            },
        ]

    def Run(self) -> None:
        self._ConfigureLogger()
        runLogger = self._Logger("Run")
        runLogger.info(
            "온톨로지 smoke를 시작합니다 ontology_root={}",
            self._ontologyRootPath,
        )

        contextBuilder = OntologyContextBuilder(self._ontologyRootPath)

        self._LogStepHeader(1, 13, "온톨로지 마크다운 문서를 로드합니다")
        documentSummary = self._RunDocumentLoadSmoke(contextBuilder)

        self._LogStepHeader(
            2,
            13,
            "문서 검색 결과가 LLM 요청 컨텍스트로 변환되는지 확인합니다",
        )
        queryResults = [
            self._RunQuerySmoke(contextBuilder, queryCase)
            for queryCase in self._smokeQueries
        ]

        self._LogStepHeader(3, 13, "문서 참조 관계와 frontmatter 메타데이터를 검증합니다")
        validationSummary = self._RunValidationSmoke(contextBuilder)

        self._LogStepHeader(4, 13, "문서에 선언된 CSV 데이터 경로를 확인합니다")
        resourceSummary = self._RunResourceResolutionSmoke(contextBuilder)

        self._LogStepHeader(
            5,
            13,
            "상품 정보로 정적/semantic CN 후보를 병렬 검색하고 점수를 설명합니다",
        )
        classificationCandidateSummary = self._RunClassificationCandidateSmoke()

        self._LogStepHeader(6, 13, "후보 검토용 LLM 요청 JSON 구조를 만듭니다")
        classificationRequestSummary = self._RunClassificationRequestSmoke(
            contextBuilder,
        )

        self._LogStepHeader(7, 13, "메인 LLM 후보 검토 응답을 생성하고 검증합니다")
        llmResponseValidationSummary = self._RunLlmResponseValidationSmoke(
            contextBuilder,
        )

        self._LogStepHeader(8, 13, "후보 판단에 사용할 근거 묶음을 만듭니다")
        evidencePackageSummary = self._RunEvidencePackageSmoke(contextBuilder)

        self._LogStepHeader(9, 13, "후보 리뷰 정책을 fixture 시나리오로 검증합니다")
        decisionPolicySummary = self._RunStage1DecisionPolicySmoke(contextBuilder)

        self._LogStepHeader(10, 13, "fixture 시나리오의 다음 파이프라인 동작을 확인합니다")
        traversalControllerSummary = self._RunStage1TraversalControllerSmoke(
            decisionPolicySummary,
        )

        self._LogStepHeader(11, 13, "백트래킹 예외 경로를 fixture 시나리오로 검증합니다")
        backtrackingRetrySummary = self._RunStage1BacktrackingRetrySmoke(
            contextBuilder,
            decisionPolicySummary,
        )

        self._LogStepHeader(12, 13, "선택된 LLM 후보 검토 결과를 후보 산출 요약으로 정리합니다")
        recommendationReportSummary = self._RunStage1RecommendationReportSmoke(
            llmResponseValidationSummary,
            backtrackingRetrySummary,
        )

        self._LogStepHeader(13, 13, "선택된 LLM 후보 검토 결과를 검토용 JSON 패키지로 만듭니다")
        humanReviewPackageSummary = self._RunStage1HumanReviewPackageSmoke(
            llmResponseValidationSummary,
            backtrackingRetrySummary,
        )

        summary = {
            "ontology_root_path": str(self._ontologyRootPath),
            "document_summary": documentSummary,
            "query_results": queryResults,
            "validation_summary": validationSummary,
            "resource_summary": resourceSummary,
            "classification_candidate_summary": classificationCandidateSummary,
            "classification_request_summary": classificationRequestSummary,
            "llm_response_validation_summary": llmResponseValidationSummary,
            "evidence_package_summary": evidencePackageSummary,
            "stage1_decision_policy_summary": decisionPolicySummary,
            "stage1_traversal_controller_summary": traversalControllerSummary,
            "stage1_backtracking_retry_summary": backtrackingRetrySummary,
            "stage1_recommendation_report_summary": recommendationReportSummary,
            "stage1_human_review_package_summary": humanReviewPackageSummary,
        }
        self._LogSummary(summary)
        if self._writeSummaryArtifact:
            self._WriteSummaryArtifact(summary)

    def _RunDocumentLoadSmoke(
        self,
        contextBuilder: OntologyContextBuilder,
    ) -> Dict[str, Any]:
        documents = contextBuilder.LoadDocuments()
        retrievalDocuments = contextBuilder.LoadRetrievalDocuments(
            phaseId=self._phaseId,
        )
        result = {
            "document_count": len(documents),
            "phase_id": self._phaseId,
            "retrieval_document_count": len(retrievalDocuments),
            "retrieval_document_paths": [
                document.relativePath for document in retrievalDocuments
            ],
        }
        self._Logger("Stage1DocumentLoad").info(
            "documents={} retrieval_documents={} phase_id={}",
            result["document_count"],
            result["retrieval_document_count"],
            result["phase_id"],
        )
        return result

    def _RunQuerySmoke(
        self,
        contextBuilder: OntologyContextBuilder,
        queryCase: Dict[str, str],
    ) -> Dict[str, Any]:
        context = contextBuilder.BuildContext(
            query=queryCase["query"],
            phaseId=queryCase["phase_id"],
            topK=self._topK,
            maxResultCount=self._maxResultCount,
        )
        llmRequest = LlmRequestBuilder().BuildRequest(
            userPrompt=queryCase["user_prompt"],
            packagedContext=context,
        )
        contextData = context.model_dump(mode="json", by_alias=True)
        result = {
            "name": queryCase["name"],
            "phase_id": queryCase["phase_id"],
            "query": queryCase["query"],
            "status": {
                "has_context": len(context.contextChunks) > 0,
                "request_context_chunk_count": len(llmRequest.contextChunks),
            },
            "context": {
                "selected_result_count": len(context.selectedResults),
                "total_token_estimate": context.totalTokenEstimate,
                "omitted_result_count": context.omittedResultCount,
                "warnings": list(context.warnings),
                "selected_chunk_preview": [
                    {
                        "score": selectedResult["score"],
                        "relative_path": selectedResult["chunk"]["relative_path"],
                        "heading_path": selectedResult["chunk"]["heading_path"],
                    }
                    for selectedResult in contextData["selected_results"][:3]
                ],
            },
            "request": {
                "response_format": llmRequest.responseFormat.value,
                "system_prompt_length": len(llmRequest.systemPrompt or ""),
                "user_prompt": llmRequest.userPrompt,
            },
        }
        self._Logger("Stage2ContextRequest").info(
            (
                "query={} has_context={} selected={} request_chunks={} "
                "tokens={} omitted={} warnings={}"
            ),
            result["name"],
            result["status"]["has_context"],
            result["context"]["selected_result_count"],
            result["status"]["request_context_chunk_count"],
            result["context"]["total_token_estimate"],
            result["context"]["omitted_result_count"],
            len(result["context"]["warnings"]),
        )
        return result

    def _RunValidationSmoke(
        self,
        contextBuilder: OntologyContextBuilder,
    ) -> Dict[str, Any]:
        documents = contextBuilder.LoadDocuments()
        validationReport = OntologyGraphValidator(
            self._ontologyRootPath,
        ).Validate(documents)
        validationData = validationReport.model_dump(mode="json", by_alias=True)
        issues = list(validationData["issues"])
        result = {
            "is_valid": validationData["is_valid"],
            "error_count": validationData["error_count"],
            "warning_count": validationData["warning_count"],
            "issues": issues,
            "issues_preview": issues[:self._validationIssuePreviewCount],
        }
        validationLogger = self._Logger("Stage3GraphValidation")
        validationLogger.info(
            "valid={} errors={} warnings={}",
            result["is_valid"],
            result["error_count"],
            result["warning_count"],
        )
        if result["issues_preview"]:
            firstIssue = result["issues_preview"][0]
            validationLogger.warning(
                "first_issue severity={} code={} path={} message={}",
                firstIssue["severity"],
                firstIssue["issue_code"],
                firstIssue["relative_path"],
                firstIssue["message"],
            )
        return result

    def _RunResourceResolutionSmoke(
        self,
        contextBuilder: OntologyContextBuilder,
    ) -> Dict[str, Any]:
        documents = contextBuilder.LoadDocuments()
        resourceReport = OntologyResourceResolver(
            self._ontologyRootPath,
            projectRootPath=PROJECT_ROOT_PATH,
        ).Resolve(documents)
        resourceData = resourceReport.model_dump(mode="json", by_alias=True)
        checks = list(resourceData["data_source_checks"])
        result = {
            "is_valid": resourceData["is_valid"],
            "total_count": resourceData["total_count"],
            "loadable_count": resourceData["loadable_count"],
            "missing_count": resourceData["missing_count"],
            "invalid_count": resourceData["invalid_count"],
            "data_source_checks": checks,
            "checks_preview": checks[:self._resourceCheckPreviewCount],
        }
        resourceLogger = self._Logger("Stage4ResourceResolution")
        resourceLogger.info(
            "valid={} loadable={}/{} missing={} invalid={}",
            result["is_valid"],
            result["loadable_count"],
            result["total_count"],
            result["missing_count"],
            result["invalid_count"],
        )
        missingChecks = [
            check
            for check in result["checks_preview"]
            if not check["is_loadable"]
        ]
        if missingChecks:
            firstMissingCheck = missingChecks[0]
            resourceLogger.warning(
                "first_unloadable resource_id={} path={} error={}",
                firstMissingCheck["resource_id"],
                firstMissingCheck["declared_path"],
                firstMissingCheck["error"],
            )
        return result

    def _BuildStage1PreparedProducts(
        self,
        topK: int,
        maxProductCount: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        smokeRecords = self._LoadProductSmokeRecords()
        normalizer = ProductClassificationInputNormalizer()
        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=self._ontologyRootPath,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        semanticCandidateIndex = self._GetSemanticCandidateIndex(candidateRetriever)
        productLimit = (
            self._maxProductSmokeInputs
            if maxProductCount is None
            else maxProductCount
        )
        preparedProducts: List[Dict[str, Any]] = []
        for smokeRecord in smokeRecords[:productLimit]:
            productInput = normalizer.BuildFromKurlyPipelineResultData(smokeRecord)
            candidates = (
                candidateRetriever.FindCandidatesWithSemanticIndex(
                    productInput=productInput,
                    semanticIndex=semanticCandidateIndex,
                    heuristicTopK=topK,
                    semanticTopK=self._semanticCandidateTopK,
                    finalCandidateLimit=self._hybridCandidateLimit,
                    minSemanticScore=self._semanticMinScore,
                )
                if semanticCandidateIndex is not None
                else candidateRetriever.FindCandidates(
                    productInput,
                    topK=topK,
                )
            )
            preparedProducts.append(
                {
                    "product_input": productInput,
                    "candidates": candidates,
                    "candidate_retrieval": self._BuildCandidateRetrievalSummary(
                        candidates,
                    ),
                }
            )
        return preparedProducts

    def _GetSemanticCandidateIndex(
        self,
        candidateRetriever: CnCandidateRetriever,
    ) -> Optional[CnSemanticCandidateIndex]:
        if self._semanticCandidateIndex is not None:
            return self._semanticCandidateIndex
        if self._semanticCandidateIndexStatus is not None:
            return None

        if not self._useSemanticCandidateRetrieval:
            self._semanticCandidateIndexStatus = {
                "status": "disabled",
                "reason": "semantic candidate retrieval is disabled by appconfig",
            }
            return None

        runtimeConfig = BuildTextEmbeddingRuntimeConfig(self._embeddingConfig)
        if not runtimeConfig.enabled:
            self._semanticCandidateIndexStatus = {
                "status": "disabled",
                "reason": "embedding runtime is disabled by appconfig",
                "provider": runtimeConfig.provider.value,
                "model": runtimeConfig.modelName,
                "local_files_only": runtimeConfig.localFilesOnly,
            }
            return None

        dependencyStatus = ProbeTextEmbeddingDependency(runtimeConfig)
        if not dependencyStatus.isAvailable:
            self._semanticCandidateIndexStatus = {
                "status": "unavailable",
                "reason": dependencyStatus.message,
                "provider": dependencyStatus.provider.value,
                "model": runtimeConfig.modelName,
                "local_files_only": runtimeConfig.localFilesOnly,
                "limitations": list(dependencyStatus.limitations),
            }
            return None

        try:
            embeddingAdapter = BuildTextEmbeddingAdapter(
                runtimeConfig,
                dependencyStatus=dependencyStatus,
            )
            if embeddingAdapter is None:
                self._semanticCandidateIndexStatus = {
                    "status": "disabled",
                    "reason": "embedding adapter was not created",
                    "provider": runtimeConfig.provider.value,
                    "model": runtimeConfig.modelName,
                }
                return None

            semanticCandidateIndex = CnSemanticCandidateIndex(embeddingAdapter)
            semanticCandidateIndex.Build(candidateRetriever.LoadRowsByDomainScope())
        except (
            TextEmbeddingAdapterBuildError,
            TextEmbeddingGenerationError,
            ValueError,
        ) as exception:
            semanticStatus = (
                "unavailable"
                if runtimeConfig.localFilesOnly
                and isinstance(exception, TextEmbeddingAdapterBuildError)
                else "failed"
            )
            self._semanticCandidateIndexStatus = {
                "status": semanticStatus,
                "reason": str(exception),
                "provider": runtimeConfig.provider.value,
                "model": runtimeConfig.modelName,
                "local_files_only": runtimeConfig.localFilesOnly,
            }
            return None

        self._semanticCandidateIndex = semanticCandidateIndex
        self._semanticCandidateIndexStatus = {
            "status": "completed",
            "provider": runtimeConfig.provider.value,
            "model": runtimeConfig.modelName,
            "device": runtimeConfig.device,
            "local_files_only": runtimeConfig.localFilesOnly,
            "chunk_count": semanticCandidateIndex.chunkCount,
            "semantic_top_k": self._semanticCandidateTopK,
            "semantic_min_score": self._semanticMinScore,
            "hybrid_candidate_limit": self._hybridCandidateLimit,
            "limitations": list(dependencyStatus.limitations),
        }
        return semanticCandidateIndex

    def _BuildCandidateRetrievalSummary(
        self,
        candidates: List[CnCandidate],
    ) -> Dict[str, Any]:
        heuristicCount = sum(
            1
            for candidate in candidates
            if "heuristic" in candidate.retrievalSources
        )
        semanticCount = sum(
            1
            for candidate in candidates
            if "semantic" in candidate.retrievalSources
        )
        bothCount = sum(
            1
            for candidate in candidates
            if "heuristic" in candidate.retrievalSources
            and "semantic" in candidate.retrievalSources
        )
        return {
            "mode": (
                "hybrid"
                if self._semanticCandidateIndexStatus is not None
                and self._semanticCandidateIndexStatus.get("status") == "completed"
                else "heuristic"
            ),
            "heuristic_candidate_count": heuristicCount,
            "semantic_candidate_count": semanticCount,
            "both_source_candidate_count": bothCount,
            "semantic_index": dict(self._semanticCandidateIndexStatus or {}),
        }

    def _BuildStage1ContextEvidenceData(
        self,
        contextBuilder: OntologyContextBuilder,
        requestBuilder: Stage1RequestBuilder,
        evidencePackageBuilder: Stage1EvidencePackageBuilder,
        productInput: ProductClassificationInput,
        candidates: List[CnCandidate],
    ) -> Dict[str, Any]:
        ontologyQuery = requestBuilder.BuildOntologyQuery(productInput, candidates)
        packagedContext = contextBuilder.BuildContext(
            query=ontologyQuery,
            phaseId=self._phaseId,
            topK=self._topK,
            maxResultCount=self._maxResultCount,
        )
        evidencePackage = evidencePackageBuilder.Build(
            productInput=productInput,
            candidates=candidates,
            packagedContext=packagedContext,
        )
        return {
            "ontology_query": ontologyQuery,
            "packaged_context": packagedContext,
            "evidence_package": evidencePackage,
        }

    def _RunClassificationCandidateSmoke(self) -> Dict[str, Any]:
        smokeRecords = self._LoadProductSmokeRecords()
        preparedProducts = self._BuildStage1PreparedProducts(
            topK=self._cnCandidateTopK,
        )

        productResults: List[Dict[str, Any]] = []
        for preparedProduct in preparedProducts:
            productInput = preparedProduct["product_input"]
            candidates = preparedProduct["candidates"]
            candidateRetrieval = preparedProduct["candidate_retrieval"]
            searchText = productInput.BuildSearchText()
            semanticSearchText = productInput.BuildSemanticSearchText()
            productResults.append(
                {
                    "product_input": {
                        "product_name": productInput.productName,
                        "product_domain": productInput.productDomain,
                        "domain_scopes": list(productInput.domainScopes),
                        "notice_field_count": len(productInput.noticeFieldTexts),
                        "ocr_text_length": len(productInput.ocrText),
                    },
                    "scoring_input": {
                        "search_text_length": len(searchText),
                        "search_text_preview": self._BuildTextPreview(searchText),
                        "semantic_search_text_length": len(semanticSearchText),
                        "semantic_search_text_preview": self._BuildTextPreview(
                            semanticSearchText,
                        ),
                    },
                    "candidate_retrieval": candidateRetrieval,
                    "scoring_rule": {
                        "primary_product_evidence": (
                            "상품명, 짧은 설명, 브랜드명처럼 사용자가 실제로 "
                            "분류하려는 상품 정체성을 가장 강하게 나타내는 근거"
                        ),
                        "secondary_product_evidence": (
                            "상품고시정보, 옵션명, 정규화된 OCR 핵심 사실처럼 "
                            "상품 정체성을 보완하는 근거"
                        ),
                        "weak_ocr_evidence": (
                            "마케팅 문구, 알레르기 주의사항, 혼입 가능성처럼 "
                            "후보 탐색에는 참고하되 강하게 반영하지 않는 OCR 근거"
                        ),
                        "score_formula": (
                            "include/search/description 매칭을 primary, secondary, "
                            "weak 근거 단계별 가중치로 계산합니다."
                        ),
                        "exclude_rule_match": "score forced to 0",
                    },
                    "candidate_count": len(candidates),
                    "candidate_scores": [
                        {
                            "rank": candidateIndex,
                            "hs8": candidate.hs8,
                            "hs6_code": candidate.hs6Code,
                            "score": candidate.score,
                            "score_breakdown": candidate.scoreBreakdown,
                            "retrieval_sources": list(candidate.retrievalSources),
                            "semantic_score": candidate.semanticScore,
                            "semantic_matches": list(candidate.semanticMatches[:3]),
                            "include_rule_matches": list(candidate.includeRuleMatches),
                            "search_keyword_matches": list(
                                candidate.searchKeywordMatches,
                            ),
                            "description_matches": list(candidate.descriptionMatches),
                            "exclude_rule_matches": list(candidate.excludeRuleMatches),
                            "primary_evidence_matches": list(
                                candidate.primaryEvidenceMatches,
                            ),
                            "secondary_evidence_matches": list(
                                candidate.secondaryEvidenceMatches,
                            ),
                            "weak_evidence_matches": list(
                                candidate.weakEvidenceMatches,
                            ),
                            "combined_description": candidate.combinedDescription,
                        }
                        for candidateIndex, candidate in enumerate(
                            candidates,
                            start=1,
                        )
                    ],
                }
            )

        result = {
            "product_smoke_summary_path": str(
                self._productSmokeSummaryArtifactPath,
            ),
            "product_smoke_record_count": len(smokeRecords),
            "used_product_count": len(productResults),
            "candidate_top_k": self._cnCandidateTopK,
            "semantic_candidate_top_k": self._semanticCandidateTopK,
            "hybrid_candidate_limit": self._hybridCandidateLimit,
            "semantic_index_status": dict(self._semanticCandidateIndexStatus or {}),
            "products": productResults,
        }
        self._LogCandidateScoring(result)
        return result

    def _LogCandidateScoring(self, result: Dict[str, Any]) -> None:
        candidateLogger = self._Logger("Stage5CandidateRetrieval")
        candidateLogger.info(
            (
                "후보 검색 입력 artifact를 읽었습니다 product_records={} "
                "used_products={} heuristic_top_k={} semantic_top_k={} "
                "hybrid_limit={} semantic_status={}"
            ),
            result["product_smoke_record_count"],
            result["used_product_count"],
            result["candidate_top_k"],
            result["semantic_candidate_top_k"],
            result["hybrid_candidate_limit"],
            result["semantic_index_status"].get("status", "not_attempted"),
        )
        candidateLogger.info(
            (
                "후보 검색 규칙: 정적 후보 검색은 먼저 상품 도메인으로 CSV 범위를 제한하고, "
                "상품명/설명/브랜드는 primary 근거, 상품고시/OCR 핵심 사실은 "
                "secondary 근거, 마케팅성 OCR 문구는 weak 근거로 분리합니다. "
                "include/search/description 매칭은 근거 단계별 가중치로 계산하고, "
                "exclude_rule_keywords가 매칭되면 해당 행은 후보에서 제외합니다. "
                "semantic 후보 검색은 별도 embedding 검색으로 병렬 수행한 뒤 "
                "CN8 기준으로 정적 후보와 병합합니다."
            )
        )
        for productResult in result["products"]:
            productInput = productResult["product_input"]
            scoringInput = productResult["scoring_input"]
            candidateRetrieval = productResult["candidate_retrieval"]
            candidateCodes = [
                candidate["hs8"]
                for candidate in productResult["candidate_scores"]
            ]
            candidateLogger.info(
                (
                    "후보 검색 대상 상품: product={} domain={} 검색범위={} "
                    "mode={} 검색텍스트길이={} semantic검색텍스트길이={} "
                    "상품고시필드={} OCR텍스트길이={} 후보코드={}"
                ),
                productInput["product_name"],
                productInput["product_domain"],
                productInput["domain_scopes"],
                candidateRetrieval["mode"],
                scoringInput["search_text_length"],
                scoringInput["semantic_search_text_length"],
                productInput["notice_field_count"],
                productInput["ocr_text_length"],
                candidateCodes,
            )
            candidateLogger.info(
                "검색 텍스트 예시 product={} text={}",
                productInput["product_name"],
                scoringInput["search_text_preview"],
            )
            for candidateIndex, candidate in enumerate(
                productResult["candidate_scores"],
                start=1,
            ):
                scoreBreakdown = candidate["score_breakdown"]
                candidateLogger.info(
                    (
                        "\n[후보 점수]\n"
                        "- rank: {}\n"
                        "- hs8: {}\n"
                        "- hs6: {}\n"
                        "- retrieval_sources: {}\n"
                        "- score: {}\n"
                        "- semantic_score: {}\n"
                        "- primary 근거: {}\n"
                        "- secondary 근거: {}\n"
                        "- weak 근거: {}\n"
                        "- semantic 매칭: {}\n"
                        "- exclude 매칭: {}\n"
                        "- 후보 설명: {}"
                    ),
                    candidateIndex,
                    candidate["hs8"],
                    candidate["hs6_code"],
                    candidate["retrieval_sources"],
                    candidate["score"],
                    candidate["semantic_score"],
                    candidate["primary_evidence_matches"][:8],
                    candidate["secondary_evidence_matches"][:8],
                    candidate["weak_evidence_matches"][:8],
                    candidate["semantic_matches"],
                    candidate["exclude_rule_matches"],
                    candidate["combined_description"],
                )
                candidateLogger.info(
                    (
                        "후보 점수 계산 rank={} hs8={} include_points={} "
                        "search_points={} description_points={} "
                        "exclude_triggered={}"
                    ),
                    candidateIndex,
                    candidate["hs8"],
                    scoreBreakdown["include_rule_points"],
                    scoreBreakdown["search_keyword_points"],
                    scoreBreakdown["description_points"],
                    scoreBreakdown["exclude_rule_triggered"],
                )
            candidateLogger.info(
                "후보 검색 결과 product={} candidates={}",
                productInput["product_name"],
                productResult["candidate_count"],
            )

    def _RunClassificationRequestSmoke(
        self,
        contextBuilder: OntologyContextBuilder,
    ) -> Dict[str, Any]:
        preparedProducts = self._BuildStage1PreparedProducts(
            topK=self._cnCandidateTopK,
        )
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=self._ontologyRootPath,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        requestBuilder = Stage1RequestBuilder()

        requestResults: List[Dict[str, Any]] = []
        for preparedProduct in preparedProducts:
            productInput = preparedProduct["product_input"]
            candidates = preparedProduct["candidates"]
            if not candidates:
                requestResults.append(
                    {
                        "status": "skipped",
                        "reason": NO_CN_CANDIDATE_REASON,
                        "product_name": productInput.productName,
                        "product_domain": productInput.productDomain,
                        "candidate_count": 0,
                    }
                )
                continue

            contextEvidenceData = self._BuildStage1ContextEvidenceData(
                contextBuilder,
                requestBuilder,
                evidencePackageBuilder,
                productInput,
                candidates,
            )
            ontologyQuery = contextEvidenceData["ontology_query"]
            packagedContext = contextEvidenceData["packaged_context"]
            evidencePackage = contextEvidenceData["evidence_package"]
            reviewCandidateLimit = max(1, self._maxValidationFixtureCandidates)
            reviewCandidates = candidates[:reviewCandidateLimit]
            sampleRequestCandidates = reviewCandidates[:1]
            llmRequest = requestBuilder.BuildRequest(
                productInput=productInput,
                candidates=sampleRequestCandidates,
                packagedContext=packagedContext,
                evidencePackage=evidencePackage,
            )
            evidenceData = evidencePackage.model_dump(mode="json", by_alias=True)
            promptEvidenceData = evidencePackage.ToPromptDict(
                candidateCodes=[
                    candidate.hs8
                    for candidate in sampleRequestCandidates
                ],
            )
            requestResults.append(
                {
                    "status": "completed",
                    "product_name": productInput.productName,
                    "product_domain": productInput.productDomain,
                    "candidate_count": len(candidates),
                    "llm_review_candidate_count": len(reviewCandidates),
                    "sample_request_candidate_count": len(
                        sampleRequestCandidates,
                    ),
                    "ontology_query": ontologyQuery,
                    "ontology_context_chunk_count": len(
                        packagedContext.contextChunks,
                    ),
                    "evidence_package": {
                        "evidence_record_count": len(
                            evidenceData["evidence_records"],
                        ),
                        "common_evidence_id_count": len(
                            evidenceData["common_evidence_ids"],
                        ),
                        "candidate_evidence_id_counts": {
                            candidateCode: len(evidenceIds)
                            for candidateCode, evidenceIds in (
                                evidenceData["candidate_evidence_ids"].items()
                            )
                        },
                        "prompt_evidence_record_count": len(
                            promptEvidenceData["evidence_records"],
                        ),
                        "prompt_common_evidence_id_count": len(
                            promptEvidenceData["common_evidence_ids"],
                        ),
                        "prompt_omitted_evidence_record_count": (
                            promptEvidenceData["omitted_evidence_record_count"]
                        ),
                    },
                    "request": {
                        "response_format": llmRequest.responseFormat.value,
                        "context_chunk_count": len(llmRequest.contextChunks),
                        "system_prompt_length": len(llmRequest.systemPrompt or ""),
                        "user_prompt_length": len(llmRequest.userPrompt),
                        "generation_options": (
                            llmRequest.generationOptions.model_dump(
                                mode="json",
                                by_alias=True,
                            )
                        ),
                        "context_chunk_lengths": [
                            len(contextChunk)
                            for contextChunk in llmRequest.contextChunks
                        ],
                    },
                }
            )

        result = {
            "used_product_count": len(requestResults),
            "completed_request_count": sum(
                1
                for requestResult in requestResults
                if requestResult.get("status") == "completed"
            ),
            "requests": requestResults,
        }
        requestLogger = self._Logger("Stage6ClassificationRequest")
        requestLogger.info(
            "classification_requests={} completed={}",
            result["used_product_count"],
            result["completed_request_count"],
        )
        for requestResult in result["requests"]:
            if requestResult.get("status") == "skipped":
                requestLogger.warning(
                    "product={} domain={} status=skipped reason={}",
                    requestResult["product_name"],
                    requestResult["product_domain"],
                    requestResult["reason"],
                )
                continue
            requestData = requestResult["request"]
            evidencePackageData = requestResult["evidence_package"]
            requestLogger.info(
                (
                    "product={} domain={} candidates={} llm_review_candidates={} "
                    "response_format={} context_chunks={} ontology_chunks={} "
                    "evidence_records={}"
                ),
                requestResult["product_name"],
                requestResult["product_domain"],
                requestResult["candidate_count"],
                requestResult["llm_review_candidate_count"],
                requestData["response_format"],
                requestData["context_chunk_count"],
                requestResult["ontology_context_chunk_count"],
                evidencePackageData["evidence_record_count"],
            )
        return result

    def _RunEvidencePackageSmoke(
        self,
        contextBuilder: OntologyContextBuilder,
    ) -> Dict[str, Any]:
        preparedProducts = self._BuildStage1PreparedProducts(
            topK=self._cnCandidateTopK,
        )
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=self._ontologyRootPath,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        requestBuilder = Stage1RequestBuilder()

        productResults: List[Dict[str, Any]] = []
        for preparedProduct in preparedProducts:
            productInput = preparedProduct["product_input"]
            candidates = preparedProduct["candidates"]
            contextEvidenceData = self._BuildStage1ContextEvidenceData(
                contextBuilder,
                requestBuilder,
                evidencePackageBuilder,
                productInput,
                candidates,
            )
            evidencePackage = contextEvidenceData["evidence_package"]
            evidenceData = evidencePackage.model_dump(mode="json", by_alias=True)
            evidenceRecords = evidenceData["evidence_records"]
            productResults.append(
                {
                    "product_name": productInput.productName,
                    "product_domain": productInput.productDomain,
                    "candidate_count": len(candidates),
                    "evidence_record_count": len(evidenceRecords),
                    "common_evidence_id_count": len(
                        evidenceData["common_evidence_ids"],
                    ),
                    "bti_evidence_count": sum(
                        1
                        for evidenceRecord in evidenceRecords
                        if evidenceRecord["evidence_type"] == "bti_case_chunk"
                    ),
                    "candidate_evidence_id_counts": {
                        candidateCode: len(evidenceIds)
                        for candidateCode, evidenceIds in (
                            evidenceData["candidate_evidence_ids"].items()
                        )
                    },
                    "evidence_preview": [
                        {
                            "evidence_id": evidenceRecord["evidence_id"],
                            "evidence_type": evidenceRecord["evidence_type"],
                            "candidate_hs8": evidenceRecord["candidate_hs8"],
                            "text_length": len(evidenceRecord["text"]),
                        }
                        for evidenceRecord in evidenceRecords[:5]
                    ],
                }
            )

        result = {
            "used_product_count": len(productResults),
            "products": productResults,
        }
        evidenceLogger = self._Logger("Stage8EvidencePackage")
        evidenceLogger.info(
            "evidence_products={}",
            result["used_product_count"],
        )
        for productResult in result["products"]:
            evidenceLogger.info(
                (
                    "product={} domain={} candidates={} evidence_records={} "
                    "common_evidence={} bti_evidence={}"
                ),
                productResult["product_name"],
                productResult["product_domain"],
                productResult["candidate_count"],
                productResult["evidence_record_count"],
                productResult["common_evidence_id_count"],
                productResult["bti_evidence_count"],
            )
        return result

    def _RunLlmResponseValidationSmoke(
        self,
        contextBuilder: OntologyContextBuilder,
    ) -> Dict[str, Any]:
        validator = Stage1ResponseValidator()
        preparedProducts = self._BuildStage1PreparedProducts(
            topK=self._maxValidationFixtureCandidates,
            maxProductCount=1,
        )
        if not preparedProducts:
            result = {
                "status": "skipped",
                "reason": "product smoke artifact is empty",
                "llm_connection_enabled": self._runLlmConnectionSmoke,
            }
            self._Logger("Stage7ResponseValidation").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        requestBuilder = Stage1RequestBuilder()
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=self._ontologyRootPath,
            projectRootPath=PROJECT_ROOT_PATH,
        )

        productInput = preparedProducts[0]["product_input"]
        candidates = preparedProducts[0]["candidates"]
        if not candidates:
            result = {
                "status": "skipped",
                "reason": NO_CN_CANDIDATE_REASON,
                "product_name": productInput.productName,
                "candidate_count": 0,
                "llm_connection_enabled": self._runLlmConnectionSmoke,
            }
            self._Logger("Stage7ResponseValidation").warning(
                "status=skipped product={} reason={}",
                result["product_name"],
                result["reason"],
            )
            return result

        contextEvidenceData = self._BuildStage1ContextEvidenceData(
            contextBuilder,
            requestBuilder,
            evidencePackageBuilder,
            productInput,
            candidates,
        )
        evidencePackage = contextEvidenceData["evidence_package"]
        fixtureResponseText = self._BuildStage1FixtureResponseText(
            productInput,
            candidates,
            evidencePackage,
        )
        fixtureReport = validator.ValidateText(
            fixtureResponseText,
            productInput,
            candidates,
            evidencePackage=evidencePackage,
        )
        llmConnectionResult = self._RunOptionalLlmConnectionSmoke(
            contextBuilder=contextBuilder,
            productInput=productInput,
            candidates=candidates,
            requestBuilder=requestBuilder,
            validator=validator,
            evidencePackage=evidencePackage,
        )

        result = {
            "status": "completed",
            "product_name": productInput.productName,
            "candidate_count": len(candidates),
            "fixture_validation": fixtureReport.model_dump(mode="json", by_alias=True),
            "llm_connection": llmConnectionResult,
        }
        validationLogger = self._Logger("Stage7ResponseValidation")
        validationLogger.info(
            (
                "stage=7 fixture_valid={} fixture_errors={} "
                "llm_enabled={} llm_status={}"
            ),
            result["fixture_validation"]["is_valid"],
            result["fixture_validation"]["error_count"],
            result["llm_connection"]["enabled"],
            result["llm_connection"]["status"],
        )
        if result["llm_connection"]["status"] == "completed":
            responseValidation = result["llm_connection"]["validation"]
            responseDecision = result["llm_connection"]["decision"]
            responseTraversal = result["llm_connection"]["traversal"]
            validationLogger.info(
                (
                    "stage=7 llm_response_valid={} errors={} warnings={} "
                    "generated_text_length={} decision_status={} "
                    "priority_review_hs8={} backtracking={} next_action={}"
                ),
                responseValidation["is_valid"],
                responseValidation["error_count"],
                responseValidation["warning_count"],
                result["llm_connection"]["response"]["generated_text_length"],
                responseDecision["decision_status"],
                responseDecision["recommended_candidate_hs8"],
                responseDecision["backtracking_recommended"],
                responseTraversal["next_action"],
            )
        elif result["llm_connection"]["status"] == "failed":
            validationLogger.warning(
                "stage=7 llm_connection_error={}",
                result["llm_connection"]["error"],
            )
        return result

    def _RunStage1DecisionPolicySmoke(
        self,
        contextBuilder: OntologyContextBuilder,
    ) -> Dict[str, Any]:
        preparedProducts = self._BuildStage1PreparedProducts(
            topK=self._maxValidationFixtureCandidates,
            maxProductCount=1,
        )
        if not preparedProducts:
            result = {
                "status": "skipped",
                "reason": "product smoke artifact is empty",
            }
            self._Logger("Stage9DecisionPolicy").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        requestBuilder = Stage1RequestBuilder()
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=self._ontologyRootPath,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        validator = Stage1ResponseValidator()
        decisionPolicy = Stage1DecisionPolicy()

        productInput = preparedProducts[0]["product_input"]
        candidates = preparedProducts[0]["candidates"]
        if not candidates:
            result = {
                "status": "skipped",
                "reason": NO_CN_CANDIDATE_REASON,
                "product_name": productInput.productName,
                "candidate_count": 0,
            }
            self._Logger("Stage9DecisionPolicy").warning(
                "status=skipped product={} reason={}",
                result["product_name"],
                result["reason"],
            )
            return result

        contextEvidenceData = self._BuildStage1ContextEvidenceData(
            contextBuilder,
            requestBuilder,
            evidencePackageBuilder,
            productInput,
            candidates,
        )
        evidencePackage = contextEvidenceData["evidence_package"]
        possibleFixtureReport = validator.ValidateText(
            self._BuildStage1FixtureResponseText(
                productInput,
                candidates,
                evidencePackage,
            ),
            productInput,
            candidates,
            evidencePackage=evidencePackage,
        )
        possibleDecisionReport = decisionPolicy.BuildDecision(
            possibleFixtureReport,
            candidates,
        )
        backtrackingFixtureReport = validator.ValidateText(
            self._BuildStage1FixtureResponseText(
                productInput,
                candidates,
                evidencePackage,
                candidateStatus="unlikely_candidate",
            ),
            productInput,
            candidates,
            evidencePackage=evidencePackage,
        )
        backtrackingDecisionReport = decisionPolicy.BuildDecision(
            backtrackingFixtureReport,
            candidates,
        )
        result = {
            "status": "completed",
            "scenario_kind": "policy_fixture_decision",
            "is_main_flow": False,
            "product_name": productInput.productName,
            "candidate_count": len(candidates),
            "backtracking_policy": {
                "trigger": (
                    "validator를 통과한 LLM 후보 검토 결과에서 strong, possible, "
                    "insufficient_information 후보가 하나도 남지 않을 때 발동합니다."
                ),
                "non_trigger_cases": [
                    "LLM 응답 구조가 invalid이면 백트래킹이 아니라 LLM 응답 재시도를 요청합니다.",
                    "strong 또는 possible 후보가 남으면 human review 패키지로 넘깁니다.",
                    "insufficient_information 후보가 남으면 추가 상품 정보 요청으로 넘깁니다.",
                ],
                "candidate_scope_strategy": [
                    "현재 후보와 이미 방문한 후보 코드는 제외합니다.",
                    (
                        "현재 HS4 heading과 다른 대체 후보는 primary 또는 "
                        "secondary 근거가 있을 때만 다시 검색합니다."
                    ),
                    (
                        "대체 후보가 없으면 같은 HS4 heading 아래에서 아직 "
                        "검토하지 않은 HS6 subheading을 우선 재탐색합니다."
                    ),
                    "재시도 횟수는 stage1 traversal retry limit으로 제한합니다.",
                ],
                "output_boundary": (
                    "백트래킹은 최종 CN8 확정을 하지 않고 다음 LLM 검토/사람 검토용 "
                    "후보 묶음을 다시 만드는 정책입니다."
                ),
            },
            "possible_fixture_decision": possibleDecisionReport.model_dump(
                mode="json",
                by_alias=True,
            ),
            "backtracking_fixture_decision": (
                backtrackingDecisionReport.model_dump(
                    mode="json",
                    by_alias=True,
                )
            ),
        }
        self._Logger("Stage9DecisionPolicy").info(
            (
                "stage=9 scenario={} product={} candidates={} possible_status={} "
                "backtracking_status={} backtracking_recommended={}"
            ),
            result["scenario_kind"],
            result["product_name"],
            result["candidate_count"],
            result["possible_fixture_decision"]["decision_status"],
            result["backtracking_fixture_decision"]["decision_status"],
            result["backtracking_fixture_decision"]["backtracking_recommended"],
        )
        policyLogger = self._Logger("Stage9DecisionPolicy")
        backtrackingPolicy = result["backtracking_policy"]
        policyLogger.info(
            (
                "\n[백트래킹 정책]\n"
                "- 발동 조건:\n"
                "  {}\n"
                "- 발동하지 않는 경우:\n"
                "  1. {}\n"
                "  2. {}\n"
                "  3. {}\n"
                "- 후보 범위 재탐색 순서:\n"
                "  1. {}\n"
                "  2. {}\n"
                "  3. {}\n"
                "  4. {}\n"
                "- 출력 경계:\n"
                "  {}"
            ),
            backtrackingPolicy["trigger"],
            backtrackingPolicy["non_trigger_cases"][0],
            backtrackingPolicy["non_trigger_cases"][1],
            backtrackingPolicy["non_trigger_cases"][2],
            backtrackingPolicy["candidate_scope_strategy"][0],
            backtrackingPolicy["candidate_scope_strategy"][1],
            backtrackingPolicy["candidate_scope_strategy"][2],
            backtrackingPolicy["candidate_scope_strategy"][3],
            backtrackingPolicy["output_boundary"],
        )
        policyLogger.info(
            (
                "\n[fixture 결과 비교]\n"
                "- 일반 후보 유지 시나리오\n"
                "  strong: {}\n"
                "  possible: {}\n"
                "  insufficient: {}\n"
                "  unlikely: {}\n"
                "- 백트래킹 발동 시나리오\n"
                "  strong: {}\n"
                "  possible: {}\n"
                "  insufficient: {}\n"
                "  unlikely: {}"
            ),
            result["possible_fixture_decision"]["strong_candidate_hs8_codes"],
            result["possible_fixture_decision"]["possible_candidate_hs8_codes"],
            result["possible_fixture_decision"]["insufficient_information_hs8_codes"],
            result["possible_fixture_decision"]["unlikely_candidate_hs8_codes"],
            result["backtracking_fixture_decision"]["strong_candidate_hs8_codes"],
            result["backtracking_fixture_decision"]["possible_candidate_hs8_codes"],
            result["backtracking_fixture_decision"][
                "insufficient_information_hs8_codes"
            ],
            result["backtracking_fixture_decision"]["unlikely_candidate_hs8_codes"],
        )
        return result

    def _RunStage1TraversalControllerSmoke(
        self,
        decisionPolicySummary: Dict[str, Any],
    ) -> Dict[str, Any]:
        if decisionPolicySummary.get("status") != "completed":
            result = {
                "status": "skipped",
                "reason": "stage1 decision policy summary is unavailable",
            }
            self._Logger("Stage10TraversalController").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        preparedProducts = self._BuildStage1PreparedProducts(
            topK=self._maxValidationFixtureCandidates,
            maxProductCount=1,
        )
        if not preparedProducts:
            result = {
                "status": "skipped",
                "reason": "product smoke artifact is empty",
            }
            self._Logger("Stage10TraversalController").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=self._ontologyRootPath,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        productInput = preparedProducts[0]["product_input"]
        candidates = preparedProducts[0]["candidates"]
        controller = Stage1TraversalController()
        possibleTraversalReport = controller.BuildFromDecision(
            self._BuildStage1DecisionReportFromData(
                decisionPolicySummary["possible_fixture_decision"],
            ),
            candidates,
        )
        backtrackingDecisionReport = self._BuildStage1DecisionReportFromData(
            decisionPolicySummary["backtracking_fixture_decision"],
        )
        backtrackingTraversalReport = controller.BuildFromDecision(
            backtrackingDecisionReport,
            candidates,
        )
        backtrackingCandidates = controller.BuildBacktrackingCandidates(
            productInput=productInput,
            currentCandidates=candidates,
            decisionReport=backtrackingDecisionReport,
            candidateRetriever=candidateRetriever,
            topK=self._maxValidationFixtureCandidates,
        )
        currentHs4Codes = sorted(
            {
                candidate.hs4Code
                for candidate in candidates
                if candidate.hs4Code is not None
            }
        )
        backtrackingHs4Codes = sorted(
            {
                candidate.hs4Code
                for candidate in backtrackingCandidates
                if candidate.hs4Code is not None
            }
        )
        backtrackingStrategy = (
            "alternative_hs4_scope"
            if any(hs4Code not in currentHs4Codes for hs4Code in backtrackingHs4Codes)
            else "same_hs4_parent_scope"
            if backtrackingCandidates
            else "no_candidate"
        )
        result = {
            "status": "completed",
            "scenario_kind": "policy_fixture_traversal",
            "is_main_flow": False,
            "possible_fixture_traversal": possibleTraversalReport.model_dump(
                mode="json",
                by_alias=True,
            ),
            "backtracking_fixture_traversal": (
                backtrackingTraversalReport.model_dump(
                    mode="json",
                    by_alias=True,
                )
            ),
            "backtracking_candidate_count": len(backtrackingCandidates),
            "backtracking_candidate_codes": [
                candidate.hs8 for candidate in backtrackingCandidates
            ],
            "backtracking_scope": {
                "strategy": backtrackingStrategy,
                "current_hs4_codes": currentHs4Codes,
                "retry_hs4_codes": backtrackingHs4Codes,
                "target_level": backtrackingDecisionReport.backtrackingTargetLevel,
                "reason": backtrackingDecisionReport.backtrackingReason,
            },
            "backtracking_candidate_preview": [
                candidate.model_dump(mode="json", by_alias=True) for candidate in backtrackingCandidates[:3]
            ],
        }
        traversalLogger = self._Logger("Stage10TraversalController")
        traversalLogger.info(
            (
                "stage=10 scenario={} possible_action={} possible_status={} "
                "backtracking_action={} backtracking_status={} "
                "backtracking_candidates={} codes={}"
            ),
            result["scenario_kind"],
            result["possible_fixture_traversal"]["next_action"],
            result["possible_fixture_traversal"]["traversal_status"],
            result["backtracking_fixture_traversal"]["next_action"],
            result["backtracking_fixture_traversal"]["traversal_status"],
            result["backtracking_candidate_count"],
            result["backtracking_candidate_codes"],
        )
        traversalLogger.info(
            (
                "\n[백트래킹 범위 선택]\n"
                "- strategy: {}\n"
                "- 현재 후보 HS4: {}\n"
                "- 재탐색 후보 HS4: {}\n"
                "- target_level: {}\n"
                "- reason: {}"
            ),
            result["backtracking_scope"]["strategy"],
            result["backtracking_scope"]["current_hs4_codes"],
            result["backtracking_scope"]["retry_hs4_codes"],
            result["backtracking_scope"]["target_level"],
            result["backtracking_scope"]["reason"],
        )
        return result

    def _RunStage1BacktrackingRetrySmoke(
        self,
        contextBuilder: OntologyContextBuilder,
        decisionPolicySummary: Dict[str, Any],
    ) -> Dict[str, Any]:
        if decisionPolicySummary.get("status") != "completed":
            result = {
                "status": "skipped",
                "reason": "stage1 decision policy summary is unavailable",
            }
            self._Logger("Stage11BacktrackingRetry").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        preparedProducts = self._BuildStage1PreparedProducts(
            topK=self._maxValidationFixtureCandidates,
            maxProductCount=1,
        )
        if not preparedProducts:
            result = {
                "status": "skipped",
                "reason": "product smoke artifact is empty",
            }
            self._Logger("Stage11BacktrackingRetry").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=self._ontologyRootPath,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        requestBuilder = Stage1RequestBuilder()
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=self._ontologyRootPath,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        productInput = preparedProducts[0]["product_input"]
        currentCandidates = preparedProducts[0]["candidates"]
        if not currentCandidates:
            result = {
                "status": "skipped",
                "reason": NO_CN_CANDIDATE_REASON,
                "product_name": productInput.productName,
                "candidate_count": 0,
            }
            self._Logger("Stage11BacktrackingRetry").warning(
                "status=skipped product={} reason={}",
                result["product_name"],
                result["reason"],
            )
            return result

        currentCandidateCodes = [candidate.hs8 for candidate in currentCandidates]
        backtrackingDecisionReport = self._BuildStage1DecisionReportFromData(
            decisionPolicySummary["backtracking_fixture_decision"],
        )
        controller = Stage1TraversalController()
        backtrackingCandidates = controller.BuildBacktrackingCandidates(
            productInput=productInput,
            currentCandidates=currentCandidates,
            decisionReport=backtrackingDecisionReport,
            candidateRetriever=candidateRetriever,
            topK=self._maxValidationFixtureCandidates,
            visitedHs8Codes=currentCandidateCodes,
            completedRetryCount=self._stage1BacktrackingRetryAttempt,
            maxRetryCount=DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
        )
        currentHs4Codes = sorted(
            {
                candidate.hs4Code
                for candidate in currentCandidates
                if candidate.hs4Code is not None
            }
        )
        retryHs4Codes = sorted(
            {
                candidate.hs4Code
                for candidate in backtrackingCandidates
                if candidate.hs4Code is not None
            }
        )
        retryScopeStrategy = (
            "alternative_hs4_scope"
            if any(hs4Code not in currentHs4Codes for hs4Code in retryHs4Codes)
            else "same_hs4_parent_scope"
            if backtrackingCandidates
            else "no_candidate"
        )
        if not backtrackingCandidates:
            result = {
                "status": "skipped",
                "reason": "backtracking candidate set is empty",
                "backtracking_scope": {
                    "strategy": retryScopeStrategy,
                    "current_hs4_codes": currentHs4Codes,
                    "retry_hs4_codes": retryHs4Codes,
                    "excluded_candidate_codes": currentCandidateCodes,
                    "completed_retry_count": self._stage1BacktrackingRetryAttempt,
                    "max_retry_count": DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
                },
            }
            self._Logger("Stage11BacktrackingRetry").warning(
                (
                    "status=skipped reason={}\n"
                    "\n[백트래킹 skip 범위]\n"
                    "- strategy: {}\n"
                    "- current_hs4: {}\n"
                    "- retry_hs4: {}\n"
                    "- excluded_candidates: {}\n"
                    "- completed_retry_count: {}\n"
                    "- max_retry_count: {}"
                ),
                result["reason"],
                result["backtracking_scope"]["strategy"],
                result["backtracking_scope"]["current_hs4_codes"],
                result["backtracking_scope"]["retry_hs4_codes"],
                result["backtracking_scope"]["excluded_candidate_codes"],
                result["backtracking_scope"]["completed_retry_count"],
                result["backtracking_scope"]["max_retry_count"],
            )
            return result

        retryCandidateCodes = [candidate.hs8 for candidate in backtrackingCandidates]
        visitedCandidateCodes = [*currentCandidateCodes, *retryCandidateCodes]
        contextEvidenceData = self._BuildStage1ContextEvidenceData(
            contextBuilder,
            requestBuilder,
            evidencePackageBuilder,
            productInput,
            backtrackingCandidates,
        )
        evidencePackage = contextEvidenceData["evidence_package"]
        backtrackingSummary = {
            "initial_candidate_hs8_codes": currentCandidateCodes,
            "retry_candidate_hs8_codes": retryCandidateCodes,
            "visited_candidate_hs8_codes": visitedCandidateCodes,
            "max_retry_count": DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
            "completed_retry_count": self._stage1BacktrackingRetryAttempt + 1,
            "scope_strategy": retryScopeStrategy,
            "initial_hs4_codes": currentHs4Codes,
            "retry_hs4_codes": retryHs4Codes,
        }
        llmConnectionResult = self._RunOptionalLlmConnectionSmoke(
            contextBuilder=contextBuilder,
            productInput=productInput,
            candidates=backtrackingCandidates,
            requestBuilder=requestBuilder,
            validator=Stage1ResponseValidator(),
            evidencePackage=evidencePackage,
            backtrackingSummary=backtrackingSummary,
        )
        nextRetryCandidateCodes: List[str] = []
        nextRetryStopReason = "llm_retry_not_completed"
        if llmConnectionResult["status"] == "completed":
            retryDecisionReport = self._BuildStage1DecisionReportFromData(
                llmConnectionResult["decision"],
            )
            retryNextAction = llmConnectionResult["traversal"]["next_action"]
            if retryNextAction == "retry_llm_response":
                nextRetryStopReason = "retry_llm_response_required"
            elif retryNextAction == "backtrack_candidate_scope":
                nextRetryCandidates = controller.BuildBacktrackingCandidates(
                    productInput=productInput,
                    currentCandidates=backtrackingCandidates,
                    decisionReport=retryDecisionReport,
                    candidateRetriever=candidateRetriever,
                    topK=self._maxValidationFixtureCandidates,
                    visitedHs8Codes=visitedCandidateCodes,
                    completedRetryCount=(
                        self._stage1BacktrackingRetryAttempt + 1
                    ),
                    maxRetryCount=DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
                )
                nextRetryCandidateCodes = [
                    candidate.hs8 for candidate in nextRetryCandidates
                ]
                nextRetryStopReason = (
                    "max_retry_count_reached"
                    if (
                        self._stage1BacktrackingRetryAttempt + 1
                        >= DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT
                    )
                    else "no_unvisited_backtracking_candidates"
                    if not nextRetryCandidates
                    else None
                )
            elif retryNextAction == "prepare_human_review_package":
                nextRetryStopReason = "retry_not_required"
            else:
                nextRetryStopReason = "unhandled_retry_next_action:{0}".format(
                    retryNextAction,
                )
            if isinstance(llmConnectionResult.get("recommendation"), dict):
                llmConnectionResult["recommendation"]["backtracking_summary"][
                    "next_retry_stop_reason"
                ] = nextRetryStopReason

        result = {
            "status": "completed",
            "scenario_kind": "policy_fixture_backtracking_inference",
            "is_main_flow": False,
            "product_name": productInput.productName,
            "max_retry_count": DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
            "completed_retry_count": self._stage1BacktrackingRetryAttempt + 1,
            "visited_candidate_codes": visitedCandidateCodes,
            "retry_candidate_count": len(backtrackingCandidates),
            "retry_candidate_codes": retryCandidateCodes,
            "next_retry_candidate_codes": nextRetryCandidateCodes,
            "next_retry_stop_reason": nextRetryStopReason,
            "evidence_record_count": len(evidencePackage.evidenceRecords),
            "backtracking_scope": {
                "strategy": retryScopeStrategy,
                "initial_hs4_codes": currentHs4Codes,
                "retry_hs4_codes": retryHs4Codes,
                "excluded_candidate_codes": currentCandidateCodes,
                "visited_candidate_codes": visitedCandidateCodes,
            },
            "llm_connection": llmConnectionResult,
        }
        retryLogger = self._Logger("Stage11BacktrackingRetry")
        retryLogger.info(
            (
                "stage=11 scenario={} product={} retry_candidates={} codes={} "
                "evidence_records={} llm_status={} next_retry_stop={}"
            ),
            result["scenario_kind"],
            result["product_name"],
            result["retry_candidate_count"],
            result["retry_candidate_codes"],
            result["evidence_record_count"],
            result["llm_connection"]["status"],
            result["next_retry_stop_reason"],
        )
        retryLogger.info(
            (
                "\n[백트래킹 실행 범위]\n"
                "- strategy: {}\n"
                "- initial_hs4: {}\n"
                "- retry_hs4: {}\n"
                "- excluded_candidates: {}\n"
                "- visited_candidates: {}"
            ),
            result["backtracking_scope"]["strategy"],
            result["backtracking_scope"]["initial_hs4_codes"],
            result["backtracking_scope"]["retry_hs4_codes"],
            result["backtracking_scope"]["excluded_candidate_codes"],
            result["backtracking_scope"]["visited_candidate_codes"],
        )
        if result["llm_connection"]["status"] == "completed":
            retryTraversal = result["llm_connection"]["traversal"]
            retryLogger.info(
                "stage=11 retry_next_action={} retry_status={}",
                retryTraversal["next_action"],
                retryTraversal["traversal_status"],
            )
        return result

    def _RunStage1RecommendationReportSmoke(
        self,
        llmResponseValidationSummary: Dict[str, Any],
        backtrackingRetrySummary: Dict[str, Any],
    ) -> Dict[str, Any]:
        selectedLlmConnectionData = self._SelectStage1LlmConnection(
            llmResponseValidationSummary,
            backtrackingRetrySummary,
        )
        selectedSource = selectedLlmConnectionData["selected_source"]
        selectedLlmConnection = selectedLlmConnectionData["llm_connection"]

        result = self._BuildSelectedLlmInvalidResult(
            selectedSource,
            selectedLlmConnection,
        )
        if result is not None:
            self._Logger("Stage12RecommendationReport").warning(
                (
                    "status=skipped reason={} selected_source={} "
                    "validation_errors={} validation_warnings={}"
                ),
                result["reason"],
                result["selected_source"],
                result["validation_error_count"],
                result["validation_warning_count"],
            )
            return result

        recommendationReport = selectedLlmConnection.get("recommendation")
        if not isinstance(recommendationReport, dict):
            result = {
                "status": "skipped",
                "reason": "recommendation report is unavailable",
                "selected_source": selectedSource,
                "upstream_llm_status": selectedLlmConnection.get("status"),
                "upstream_llm_error": selectedLlmConnection.get("error"),
            }
            self._Logger("Stage12RecommendationReport").warning(
                (
                    "status=skipped reason={} selected_source={} "
                    "upstream_llm_status={} upstream_llm_error={}"
                ),
                result["reason"],
                result["selected_source"],
                result["upstream_llm_status"],
                result["upstream_llm_error"],
            )
            return result

        result = {
            "status": "completed",
            "selected_source": selectedSource,
            "recommendation_report": recommendationReport,
        }
        naturalLanguageAnswer = selectedLlmConnection.get("natural_language_answer")
        if isinstance(naturalLanguageAnswer, str) and naturalLanguageAnswer.strip():
            result["natural_language_answer"] = naturalLanguageAnswer
        recommendedCandidate = recommendationReport.get("recommended_candidate")
        recommendedHs8 = (
            recommendedCandidate.get("hs8")
            if isinstance(recommendedCandidate, dict)
            else None
        )
        self._Logger("Stage12RecommendationReport").info(
            (
                "stage=12 source={} recommendation_level={} "
                "priority_review_hs8={} comparison_candidates={} "
                "unlikely_candidates={}"
            ),
            result["selected_source"],
            recommendationReport.get("recommendation_level"),
            recommendedHs8,
            len(recommendationReport.get("retained_candidates", [])),
            len(recommendationReport.get("rejected_candidates_summary", [])),
        )
        if "natural_language_answer" in result:
            self._Logger("Stage12RecommendationReport").info(
                "선택된 LLM 후보 검토 자연어 결과\n{}",
                result["natural_language_answer"],
            )
        return result

    def _RunStage1HumanReviewPackageSmoke(
        self,
        llmResponseValidationSummary: Dict[str, Any],
        backtrackingRetrySummary: Dict[str, Any],
    ) -> Dict[str, Any]:
        selectedLlmConnectionData = self._SelectStage1LlmConnection(
            llmResponseValidationSummary,
            backtrackingRetrySummary,
        )
        selectedSource = selectedLlmConnectionData["selected_source"]
        selectedLlmConnection = selectedLlmConnectionData["llm_connection"]

        result = self._BuildSelectedLlmInvalidResult(
            selectedSource,
            selectedLlmConnection,
        )
        if result is not None:
            self._Logger("Stage13HumanReviewPackage").warning(
                (
                    "status=skipped reason={} selected_source={} "
                    "validation_errors={} validation_warnings={}"
                ),
                result["reason"],
                result["selected_source"],
                result["validation_error_count"],
                result["validation_warning_count"],
            )
            return result

        packageData = selectedLlmConnection.get("human_review_package")
        if not isinstance(packageData, dict):
            result = {
                "status": "skipped",
                "reason": "human review package is unavailable",
                "selected_source": selectedSource,
                "upstream_llm_status": selectedLlmConnection.get("status"),
                "upstream_llm_error": selectedLlmConnection.get("error"),
            }
            self._Logger("Stage13HumanReviewPackage").warning(
                (
                    "status=skipped reason={} selected_source={} "
                    "upstream_llm_status={} upstream_llm_error={}"
                ),
                result["reason"],
                result["selected_source"],
                result["upstream_llm_status"],
                result["upstream_llm_error"],
            )
            return result

        self._humanReviewPackageArtifactPath.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._humanReviewPackageArtifactPath.write_text(
            json.dumps(packageData, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        recommendation = packageData.get("recommendation_report") or {}
        recommendedCandidate = (
            recommendation.get("recommended_candidate")
            if isinstance(recommendation, dict)
            else None
        )
        recommendedHs8 = (
            recommendedCandidate.get("hs8")
            if isinstance(recommendedCandidate, dict)
            else None
        )
        result = {
            "status": "completed",
            "selected_source": selectedSource,
            "package_id": packageData.get("package_id"),
            "package_artifact_path": str(self._humanReviewPackageArtifactPath),
            "evidence_citation_count": len(packageData.get("evidence_citations", [])),
            "source_evidence_record_count": len(
                packageData.get("source_evidence_records", []),
            ),
            "validation_issue_count": len(packageData.get("validation_issues", [])),
            "priority_review_hs8": recommendedHs8,
        }
        self._Logger("Stage13HumanReviewPackage").info(
            (
                "stage=13 source={} package_id={} priority_review_hs8={} "
                "citations={} source_evidence={} validation_issues={}"
            ),
            result["selected_source"],
            result["package_id"],
            result["priority_review_hs8"],
            result["evidence_citation_count"],
            result["source_evidence_record_count"],
            result["validation_issue_count"],
        )
        return result

    def _SelectStage1LlmConnection(
        self,
        llmResponseValidationSummary: Dict[str, Any],
        backtrackingRetrySummary: Dict[str, Any],
    ) -> Dict[str, Any]:
        selectedSource = "stage7_initial_llm_review"
        selectedLlmConnection = llmResponseValidationSummary.get(
            "llm_connection",
            {},
        )
        retryLlmConnection = backtrackingRetrySummary.get(
            "llm_connection",
            {},
        )
        initialDecision = selectedLlmConnection.get("decision", {})
        initialTraversal = selectedLlmConnection.get("traversal", {})
        retryValidation = retryLlmConnection.get("validation", {})
        if (
            retryLlmConnection.get("status") == "completed"
            and retryValidation.get("is_valid") is True
            and (
                initialDecision.get("backtracking_recommended") is True
                or initialTraversal.get("next_action") == "backtrack_candidate_scope"
            )
        ):
            selectedSource = "stage11_backtracking_retry"
            selectedLlmConnection = retryLlmConnection
        return {
            "selected_source": selectedSource,
            "llm_connection": selectedLlmConnection,
        }

    def _BuildSelectedLlmInvalidResult(
        self,
        selectedSource: str,
        selectedLlmConnection: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        selectedValidation = selectedLlmConnection.get("validation", {})
        if (
            not isinstance(selectedValidation, dict)
            or "is_valid" not in selectedValidation
            or selectedValidation.get("is_valid") is True
        ):
            return None
        return {
            "status": "skipped",
            "reason": "selected llm response is invalid",
            "selected_source": selectedSource,
            "upstream_llm_status": selectedLlmConnection.get("status"),
            "validation_error_count": selectedValidation.get("error_count"),
            "validation_warning_count": selectedValidation.get("warning_count"),
            "validation_issues": selectedValidation.get("issues", []),
        }

    def _BuildStage1DecisionReportFromData(
        self,
        decisionData: Dict[str, Any],
    ) -> Stage1DecisionReport:
        return Stage1DecisionReport(
            decisionStatus=decisionData["decision_status"],
            recommendedCandidateHs8=decisionData.get("recommended_candidate_hs8"),
            strongCandidateHs8Codes=list(
                decisionData.get("strong_candidate_hs8_codes", []),
            ),
            possibleCandidateHs8Codes=list(
                decisionData.get("possible_candidate_hs8_codes", []),
            ),
            unlikelyCandidateHs8Codes=list(
                decisionData.get("unlikely_candidate_hs8_codes", []),
            ),
            insufficientInformationHs8Codes=list(
                decisionData.get("insufficient_information_hs8_codes", []),
            ),
            candidateStatusByHs8=dict(
                decisionData.get("candidate_status_by_hs8", {}),
            ),
            backtrackingRecommended=bool(
                decisionData.get("backtracking_recommended", False),
            ),
            backtrackingTargetLevel=decisionData.get("backtracking_target_level"),
            backtrackingReason=decisionData.get("backtracking_reason"),
            missingInformation=list(decisionData.get("missing_information", [])),
            evidenceRefs=list(decisionData.get("evidence_refs", [])),
            humanReviewRequired=bool(
                decisionData.get("human_review_required", True),
            ),
            limitations=list(decisionData.get("limitations", [])),
        )

    def _RunOptionalLlmConnectionSmoke(
        self,
        contextBuilder: OntologyContextBuilder,
        productInput: ProductClassificationInput,
        candidates: List[CnCandidate],
        requestBuilder: Stage1RequestBuilder,
        validator: Stage1ResponseValidator,
        evidencePackage: Stage1EvidencePackage,
        backtrackingSummary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not candidates:
            return {
                "enabled": self._runLlmConnectionSmoke,
                "status": "skipped",
                "reason": NO_CN_CANDIDATE_REASON,
            }

        runtimeConfig = BuildLlmRuntimeConfigFromEnv(
            envFilePath=PROJECT_ROOT_PATH / ".env",
            projectRootPath=PROJECT_ROOT_PATH,
        )
        dependencyStatus = ProbeRuntimeDependency(runtimeConfig)
        baseResult = {
            "enabled": self._runLlmConnectionSmoke,
            "runtime_kind": runtimeConfig.runtimeKind.value,
            "model_name": runtimeConfig.modelName,
            "endpoint_url": runtimeConfig.endpointUrl,
            "dependency_available": dependencyStatus.isAvailable,
            "dependency_message": dependencyStatus.message,
            "dependency_limitations": list(dependencyStatus.limitations),
        }

        if not self._runLlmConnectionSmoke:
            return {
                **baseResult,
                "status": "skipped",
                "reason": (
                    "Set [ontology_smoke].run_llm_connection_smoke=true in "
                    ".appconfig to call the configured LLM runtime."
                ),
            }

        if not dependencyStatus.isAvailable:
            return {
                **baseResult,
                "status": "skipped",
                "reason": dependencyStatus.message,
            }

        try:
            adapter = BuildRuntimeAdapter(
                runtimeConfig,
                dependencyStatus=dependencyStatus,
            )
            candidateReviews: List[Dict[str, Any]] = []
            notEnoughInformation: List[str] = []
            responseSummaries: List[Dict[str, Any]] = []
            validationIssues: List[Stage1ResponseValidationIssue] = []

            for candidate in candidates:
                reviewCandidates = [candidate]
                ontologyQuery = requestBuilder.BuildOntologyQuery(
                    productInput,
                    reviewCandidates,
                )
                packagedContext = contextBuilder.BuildContext(
                    query=ontologyQuery,
                    phaseId=self._phaseId,
                    topK=self._topK,
                    maxResultCount=self._maxResultCount,
                )
                llmRequest = requestBuilder.BuildRequest(
                    productInput=productInput,
                    candidates=reviewCandidates,
                    packagedContext=packagedContext,
                    evidencePackage=evidencePackage,
                )
                try:
                    llmResponse = adapter.Generate(llmRequest)
                except RuntimeGenerationError as error:
                    validationIssue = Stage1ResponseValidationIssue(
                        severity="error",
                        issueCode="candidate_llm_generation_failed",
                        fieldPath=(
                            "classification_result.candidate_reviews[{0}]"
                        ).format(candidate.hs8),
                        message=(
                            "LLM generation failed for candidate {0}: {1}"
                        ).format(candidate.hs8, error),
                    )
                    validationIssues.append(validationIssue)
                    responseSummaries.append(
                        {
                            "candidate_hs8": candidate.hs8,
                            "status": "failed",
                            "error": str(error),
                            "generated_text_length": 0,
                            "generated_text_preview": "",
                            "runtime_kind": runtimeConfig.runtimeKind.value,
                            "model_name": runtimeConfig.modelName,
                            "response_format": llmRequest.responseFormat.value,
                            "finish_reason": "generation_failed",
                            "provider_finish_reason": None,
                            "token_usage": {
                                "input_tokens": None,
                                "output_tokens": None,
                                "total_tokens": None,
                            },
                            "limitations": [str(error)],
                            "validation": Stage1ResponseValidationReport(
                                isValid=False,
                                parsedResponse={},
                                issues=[validationIssue],
                            ).model_dump(mode="json", by_alias=True),
                        }
                    )
                    continue

                candidateValidationReport = validator.ValidateResponse(
                    llmResponse,
                    productInput,
                    reviewCandidates,
                    evidencePackage=evidencePackage,
                )
                validationIssues.extend(candidateValidationReport.issues)

                parsedResponse = candidateValidationReport.parsedResponse
                classificationResult = (
                    parsedResponse.get("classification_result")
                    if isinstance(parsedResponse, dict)
                    else {}
                )
                if not isinstance(classificationResult, dict):
                    classificationResult = {}

                candidateReviewData = classificationResult.get("candidate_reviews")
                if isinstance(candidateReviewData, list):
                    candidateReviews.extend(
                        review
                        for review in candidateReviewData
                        if (
                            isinstance(review, dict)
                            and review.get("hs8") == candidate.hs8
                        )
                    )

                missingData = classificationResult.get("not_enough_information")
                if isinstance(missingData, list):
                    notEnoughInformation.extend(
                        item for item in missingData if isinstance(item, str)
                    )

                responseSummaries.append(
                    {
                        "candidate_hs8": candidate.hs8,
                        "status": "completed",
                        "generated_text_length": len(llmResponse.generatedText),
                        "generated_text_preview": self._BuildTextPreview(
                            llmResponse.generatedText,
                        ),
                        "runtime_kind": llmResponse.runtimeKind.value,
                        "model_name": llmResponse.modelName,
                        "response_format": llmResponse.responseFormat.value,
                        "finish_reason": llmResponse.finishReason.value,
                        "provider_finish_reason": llmResponse.providerFinishReason,
                        "token_usage": llmResponse.tokenUsage.model_dump(
                            mode="json",
                            by_alias=True,
                        ),
                        "limitations": list(llmResponse.limitations),
                        "validation": candidateValidationReport.model_dump(
                            mode="json",
                            by_alias=True,
                        ),
                    }
                )

            combinedResponse = {
                "classification_result": {
                    "product_name": productInput.productName,
                    "product_domain": productInput.productDomain,
                    "domain_scopes": list(productInput.domainScopes),
                    "candidate_reviews": candidateReviews,
                    "not_enough_information": notEnoughInformation,
                    "recommended_next_action": "prepare_human_review_package",
                    "human_review_warning": (
                        "This is a candidate review package for human review, "
                        "not a final legal or customs determination."
                    ),
                }
            }
            combinedValidationReport = validator.ValidateText(
                json.dumps(combinedResponse, ensure_ascii=False),
                productInput,
                candidates,
                evidencePackage=evidencePackage,
            )
            validationIssues.extend(combinedValidationReport.issues)
            validationReport = Stage1ResponseValidationReport(
                isValid=not any(
                    issue.severity == "error"
                    for issue in validationIssues
                ),
                parsedResponse=combinedValidationReport.parsedResponse,
                issues=validationIssues,
            )
            decisionReport = Stage1DecisionPolicy().BuildDecision(
                validationReport,
                candidates,
            )
            traversalReport = Stage1TraversalController().BuildFromDecision(
                decisionReport,
                candidates,
            )
            recommendationReport = (
                Stage1RecommendationReportBuilder().Build(
                    productInput=productInput,
                    candidates=candidates,
                    validationReport=validationReport,
                    decisionReport=decisionReport,
                    traversalReport=traversalReport,
                    evidencePackage=evidencePackage,
                    backtrackingSummary=backtrackingSummary,
                )
            )
            selectedSource = (
                "stage11_backtracking_retry"
                if backtrackingSummary is not None
                else "stage7_initial_llm_review"
            )
            humanReviewPackage = Stage1HumanReviewPackageBuilder().Build(
                productInput=productInput,
                recommendationReport=recommendationReport,
                validationReport=validationReport,
                evidencePackage=evidencePackage,
                selectedSource=selectedSource,
            )
            naturalLanguageAnswer = self._BuildNaturalLlmAnswer(
                productInput=productInput,
                candidates=candidates,
                validationReportData=validationReport.model_dump(mode="json", by_alias=True),
                decisionReportData=decisionReport.model_dump(
                    mode="json",
                    by_alias=True,
                ),
                traversalReportData=traversalReport.model_dump(
                    mode="json",
                    by_alias=True,
                ),
            )
        except (RuntimeAdapterBuildError, RuntimeGenerationError) as error:
            return {
                **baseResult,
                "status": "failed",
                "error": str(error),
            }

        completedResponseSummaries = [
            responseSummary
            for responseSummary in responseSummaries
            if responseSummary.get("status") == "completed"
        ]
        responseMetadataSource = (
            completedResponseSummaries[0]
            if completedResponseSummaries
            else responseSummaries[0]
        )
        finishReasonSet = {
            responseSummary["finish_reason"]
            for responseSummary in responseSummaries
        }
        providerFinishReasonSet = {
            responseSummary["provider_finish_reason"]
            for responseSummary in responseSummaries
        }
        tokenUsage = {}
        for tokenKey in ["input_tokens", "output_tokens", "total_tokens"]:
            tokenValues = [
                responseSummary.get("token_usage", {}).get(tokenKey)
                for responseSummary in responseSummaries
                if isinstance(
                    responseSummary.get("token_usage", {}).get(tokenKey),
                    int,
                )
            ]
            tokenUsage[tokenKey] = sum(tokenValues) if tokenValues else None

        return {
            **baseResult,
            "status": "completed",
            "response": {
                "reviewed_candidate_count": len(candidates),
                "reviewed_candidate_hs8_codes": [
                    candidate.hs8 for candidate in candidates
                ],
                "generated_response_count": len(responseSummaries),
                "generated_text_length": sum(
                    responseSummary["generated_text_length"]
                    for responseSummary in responseSummaries
                ),
                "runtime_kind": responseMetadataSource["runtime_kind"],
                "model_name": responseMetadataSource["model_name"],
                "response_format": responseMetadataSource["response_format"],
                "finish_reason": (
                    next(iter(finishReasonSet))
                    if len(finishReasonSet) == 1
                    else "mixed"
                ),
                "provider_finish_reason": (
                    next(iter(providerFinishReasonSet))
                    if len(providerFinishReasonSet) == 1
                    else "mixed"
                ),
                "finish_reasons": [
                    responseSummary["finish_reason"]
                    for responseSummary in responseSummaries
                ],
                "provider_finish_reasons": [
                    responseSummary["provider_finish_reason"]
                    for responseSummary in responseSummaries
                ],
                "token_usage": tokenUsage,
                "candidate_responses": responseSummaries,
            },
            "validation": validationReport.model_dump(mode="json", by_alias=True),
            "decision": decisionReport.model_dump(mode="json", by_alias=True),
            "traversal": traversalReport.model_dump(mode="json", by_alias=True),
            "recommendation": recommendationReport.model_dump(mode="json", by_alias=True),
            "human_review_package": humanReviewPackage.model_dump(
                mode="json",
                by_alias=True,
            ),
            "natural_language_answer": naturalLanguageAnswer,
        }

    def _BuildNaturalLlmAnswer(
        self,
        productInput: ProductClassificationInput,
        candidates: List[CnCandidate],
        validationReportData: Dict[str, Any],
        decisionReportData: Dict[str, Any],
        traversalReportData: Dict[str, Any],
    ) -> str:
        candidateByHs8 = {candidate.hs8: candidate for candidate in candidates}
        parsedResponse = validationReportData.get("parsed_response")
        classificationResult = (
            parsedResponse.get("classification_result")
            if isinstance(parsedResponse, dict)
            else {}
        )
        if not isinstance(classificationResult, dict):
            classificationResult = {}

        recommendedHs8 = decisionReportData.get("recommended_candidate_hs8")
        recommendedCandidate = candidateByHs8.get(recommendedHs8)
        lines = [
            "상품: {0}".format(productInput.productName or "상품명 없음"),
            "검토 상태: {0}".format(decisionReportData.get("decision_status")),
        ]
        if recommendedCandidate is not None:
            lines.append(
                "우선 검토 후보: {0} ({1})".format(
                    recommendedCandidate.hs8,
                    recommendedCandidate.combinedDescription,
                )
            )
        else:
            lines.append("우선 검토 후보: 아직 하나로 좁히지 못했습니다.")

        candidateReviews = classificationResult.get("candidate_reviews")
        if isinstance(candidateReviews, list):
            lines.append("후보별 LLM 판단:")
            for candidateReview in candidateReviews[:5]:
                if not isinstance(candidateReview, dict):
                    continue
                hs8 = candidateReview.get("hs8")
                candidate = candidateByHs8.get(hs8)
                candidateLabel = (
                    candidate.combinedDescription
                    if candidate is not None
                    else "후보 설명 없음"
                )
                reason = candidateReview.get("reason")
                if not isinstance(reason, str) or reason.strip() == "":
                    reason = "판단 이유가 비어 있습니다."
                lines.append(
                    "- {0}: {1}. {2} 이유: {3}".format(
                        hs8,
                        candidateReview.get("status"),
                        candidateLabel,
                        NormalizeWhitespace(reason),
                    )
                )

        missingInformation = classificationResult.get("not_enough_information")
        if isinstance(missingInformation, list) and missingInformation:
            lines.append("추가 확인 필요:")
            for item in missingInformation[:5]:
                if isinstance(item, str) and item.strip() != "":
                    lines.append("- {0}".format(NormalizeWhitespace(item)))

        nextAction = classificationResult.get("recommended_next_action")
        if isinstance(nextAction, str) and nextAction.strip() != "":
            lines.append("다음 조치: {0}".format(NormalizeWhitespace(nextAction)))

        traversalAction = traversalReportData.get("next_action")
        if isinstance(traversalAction, str) and traversalAction.strip() != "":
            lines.append("파이프라인 다음 동작: {0}".format(traversalAction))

        humanReviewWarning = classificationResult.get("human_review_warning")
        if isinstance(humanReviewWarning, str) and humanReviewWarning.strip() != "":
            lines.append(
                "검토 주의: {0}".format(NormalizeWhitespace(humanReviewWarning))
            )
        return "\n".join(lines)

    def _BuildStage1FixtureResponseText(
        self,
        productInput: ProductClassificationInput,
        candidates: List[CnCandidate],
        evidencePackage: Stage1EvidencePackage,
        candidateStatus: str = "possible_candidate",
    ) -> str:
        candidateReviews: List[Dict[str, Any]] = []
        for candidate in candidates:
            candidateData = candidate.model_dump(mode="json", by_alias=True)
            codeHierarchy = candidateData.get("code_hierarchy", {})
            classificationPathReview = {}
            if isinstance(codeHierarchy, dict):
                for level in ["hs2", "hs4", "hs6", "cn8"]:
                    levelData = codeHierarchy.get(level, {})
                    classificationPathReview[level] = {
                        "code": (
                            levelData.get("code")
                            if isinstance(levelData, dict)
                            else None
                        ),
                        "consistency": "needs_review",
                        "comment": (
                            "Smoke fixture keeps hierarchy review explicit; "
                            "actual consistency must be inferred by LLM and "
                            "confirmed by human review."
                        ),
                    }

            similarEbtiCases = []
            for evidenceRecord in evidencePackage.evidenceRecords:
                if evidenceRecord.candidateHs8 != candidate.hs8:
                    continue
                if evidenceRecord.evidenceType != "bti_case_chunk":
                    continue
                similarEbtiCases.append(
                    {
                        "evidence_ref": evidenceRecord.evidenceId,
                        "similarity_comment": (
                            "Smoke fixture references a BTI case mapped to the "
                            "same candidate for comparative review."
                        ),
                        "difference_comment": (
                            "Actual product-specific differences must be checked "
                            "from product facts and BTI evidence text."
                        ),
                    }
                )
                break

            candidateReviews.append(
                {
                    "hs8": candidate.hs8,
                    "hs6_code": candidate.hs6Code,
                    "status": candidateStatus,
                    "supporting_product_facts": [
                        "Smoke fixture uses the candidate card and product collection result.",
                    ],
                    "conflicting_or_exclusion_facts": [],
                    "missing_information": [
                        "Human review must confirm classification-specific facts.",
                    ],
                    "evidence_refs": self._BuildStage1FixtureEvidenceRefs(
                        candidate,
                        evidencePackage,
                    ),
                    "classification_path_review": classificationPathReview,
                    "classification_rule_review": {
                        "include_rule_comment": (
                            "Review include_rule_keywords against product facts."
                        ),
                        "exclude_rule_comment": (
                            "Review exclude_rule_keywords as rejection conditions."
                        ),
                        "hard_condition_comment": (
                            "Review hard_conditions before accepting the candidate."
                        ),
                    },
                    "similar_ebti_cases": similarEbtiCases,
                    "reason": (
                        "Fixture response for validator smoke; not an actual "
                        "classification decision."
                    ),
                    "human_review_required": True,
                }
            )

        responseData = {
            "classification_result": {
                "product_name": productInput.productName,
                "product_domain": productInput.productDomain,
                "domain_scopes": list(productInput.domainScopes),
                "candidate_reviews": candidateReviews,
                "not_enough_information": [
                    "Official classification must be reviewed by a human.",
                ],
                "recommended_next_action": (
                    "Review candidate evidence and missing product facts."
                ),
                "human_review_warning": (
                    "This is not a final legal or customs determination."
                ),
            }
        }
        return json.dumps(responseData, ensure_ascii=False, indent=2)

    def _BuildStage1FixtureEvidenceRefs(
        self,
        candidate: CnCandidate,
        evidencePackage: Stage1EvidencePackage,
    ) -> List[str]:
        candidateEvidenceIds = list(
            evidencePackage.candidateEvidenceIds.get(candidate.hs8, []),
        )
        commonEvidenceIds = [
            evidenceId
            for evidenceId in evidencePackage.commonEvidenceIds
            if evidenceId in candidateEvidenceIds
        ]
        candidateSpecificEvidenceIds = [
            evidenceRecord.evidenceId
            for evidenceRecord in evidencePackage.evidenceRecords
            if evidenceRecord.candidateHs8 == candidate.hs8
            and evidenceRecord.evidenceId in candidateEvidenceIds
        ]
        return [
            *commonEvidenceIds[:1],
            *candidateSpecificEvidenceIds[:1],
        ]

    def _LogSummary(self, summary: Dict[str, Any]) -> None:
        summaryLogger = self._Logger("_LogSummary")
        successfulQueryCount = sum(
            1
            for queryResult in summary["query_results"]
            if queryResult["status"]["has_context"]
        )
        summaryLogger.info(
            (
                "summary document_count={} retrieval_document_count={} "
                "query_context_ok={}/{} validation_valid={} "
                "validation_errors={} validation_warnings={} "
                "resources_valid={} resources_loadable={}/{} "
                "classification_products={} classification_requests={} "
                "llm_response_validation_status={} evidence_products={} "
                "decision_policy_status={} traversal_controller_status={} "
                "backtracking_retry_status={} recommendation_report_status={} "
                "human_review_package_status={}"
            ),
            summary["document_summary"]["document_count"],
            summary["document_summary"]["retrieval_document_count"],
            successfulQueryCount,
            len(summary["query_results"]),
            summary["validation_summary"]["is_valid"],
            summary["validation_summary"]["error_count"],
            summary["validation_summary"]["warning_count"],
            summary["resource_summary"]["is_valid"],
            summary["resource_summary"]["loadable_count"],
            summary["resource_summary"]["total_count"],
            summary["classification_candidate_summary"]["used_product_count"],
            summary["classification_request_summary"]["used_product_count"],
            summary["llm_response_validation_summary"]["status"],
            summary["evidence_package_summary"]["used_product_count"],
            summary["stage1_decision_policy_summary"]["status"],
            summary["stage1_traversal_controller_summary"]["status"],
            summary["stage1_backtracking_retry_summary"]["status"],
            summary["stage1_recommendation_report_summary"]["status"],
            summary["stage1_human_review_package_summary"]["status"],
        )

    def _LogStepHeader(self, stepIndex: int, totalStepCount: int, title: str) -> None:
        self._Logger("Run").info(
            "\n\n========== STEP {}/{} ==========\n{}\n==============================",
            stepIndex,
            totalStepCount,
            title,
        )

    def _WriteSummaryArtifact(self, summary: Dict[str, Any]) -> None:
        self._summaryArtifactPath.parent.mkdir(parents=True, exist_ok=True)
        self._summaryArtifactPath.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._Logger("_WriteSummaryArtifact").info(
            "summary_artifact_path={}",
            self._summaryArtifactPath,
        )

    def _LoadProductSmokeRecords(self) -> List[Dict[str, Any]]:
        if not self._productSmokeSummaryArtifactPath.exists():
            return []
        try:
            rawData = json.loads(
                self._productSmokeSummaryArtifactPath.read_text(
                    encoding="utf-8",
                )
            )
        except Exception:
            return []

        rawRecords: List[Any]
        if isinstance(rawData, list):
            rawRecords = rawData
        elif isinstance(rawData, dict):
            rawRecords = [rawData]
        else:
            return []

        productSmokeRecords: List[Dict[str, Any]] = []
        for rawRecord in rawRecords:
            if not isinstance(rawRecord, dict):
                continue
            try:
                validatedRecord = ProductSmokeSummaryPayload.model_validate(rawRecord)
            except ValidationError:
                continue
            productSmokeRecords.append(
                validatedRecord.model_dump(
                    mode="json",
                    exclude_none=True,
                )
            )
        return productSmokeRecords

    def _BuildTextPreview(self, text: str) -> str:
        if len(text) <= self._textPreviewCharacters:
            return text
        return f"{text[:self._textPreviewCharacters]}..."

    def _ConfigureLogger(self) -> None:
        logger.remove()
        logger.level("INFO", color="<green>")
        logger.level("WARNING", color="<yellow>")
        logger.level("ERROR", color="<red>")
        logger.configure(
            extra={
                "className": "OntologySmokeRunner",
                "functionName": "Run",
            }
        )
        logger.add(
            sys.stderr,
            format=(
                "<level>[{level}]</level> "
                "<cyan>{extra[className]}::{extra[functionName]}: {message}</cyan>"
            ),
            level="INFO",
            colorize=True,
        )

    def _Logger(self, functionName: str) -> Any:
        return logger.bind(
            className=self.__class__.__name__,
            functionName=functionName,
        )


if __name__ == "__main__":
    OntologySmokeRunner().Run()
