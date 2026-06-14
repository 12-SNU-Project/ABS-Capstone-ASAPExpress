"""Ontology context/request builder runtime smoke.

이 파일은 core 관련 smoke를 단계별로 누적하는 단일 진입점이다.
새 smoke 단계가 필요하면 별도 파일을 만들지 말고 이 runner에 단계를 추가한다.
"""

import json
import shutil
import sys
import termios
import tty
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import pandas as pd
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
    BuildTextEmbeddingAdapter,
    BuildTextEmbeddingRuntimeConfig,
    ProbeTextEmbeddingDependency,
    TextEmbeddingAdapterBuildError,
    TextEmbeddingGenerationError,
)
from eu_export.app_config import LoadAppConfig  # noqa: E402
from eu_export.core import (  # noqa: E402
    CnCandidate,
    CnCandidateRetriever,
    CnSemanticCandidateIndex,
    LlmRequestBuilder,
    OntologyContextBuilder,
    OntologyGraphValidator,
    OntologyResourceResolver,
)
from eu_export.input_process import ProductInputAdapter  # noqa: E402
from eu_export.utils import NormalizeWhitespace  # noqa: E402


ANSWER_PRODUCT_URL_COLUMN = "상품 상세"
ANSWER_CODE_COLUMN = "미국 HS Code"
ANSWER_EVALUATION_LOG_PREVIEW_COUNT = 10


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
    """core 문서 로드, 검색 context, LLM request 생성을 확인한다."""

    def __init__(self) -> None:
        appConfig = LoadAppConfig(PROJECT_ROOT_PATH)
        pathConfig = appConfig.paths
        smokeConfig = appConfig.ontology_smoke
        embeddingConfig = appConfig.embedding
        kurlySmokeConfig = appConfig.kurly_smoke

        self._ontologyRootPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            pathConfig.ontology_root,
        )
        self._summaryArtifactPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            pathConfig.ontology_smoke_summary_artifact,
        )
        self._productSmokeSummaryArtifactPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            pathConfig.kurly_smoke_summary_artifact,
        )
        self._answerCsvPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            smokeConfig.answer_csv_path,
        )

        self._phaseId = smokeConfig.phase_id
        self._topK = smokeConfig.top_k
        self._maxResultCount = smokeConfig.max_result_count
        self._cnCandidateTopK = smokeConfig.cn_candidate_top_k
        self._maxProductSmokeInputs = smokeConfig.max_product_smoke_inputs
        self._writeSummaryArtifact = smokeConfig.write_summary_artifact
        self._runKurlySmokeBeforeOntology = (
            smokeConfig.run_kurly_smoke_before_ontology
        )
        self._textPreviewCharacters = smokeConfig.text_preview_characters
        self._validationIssuePreviewCount = smokeConfig.validation_issue_preview_count
        self._resourceCheckPreviewCount = smokeConfig.resource_check_preview_count
        self._embeddingConfig = embeddingConfig
        self._useSemanticCandidateRetrieval = (
            smokeConfig.use_semantic_candidate_retrieval
        )
        self._semanticCandidateTopK = smokeConfig.semantic_candidate_top_k
        self._semanticMinScore = smokeConfig.semantic_min_score
        self._hybridCandidateLimit = smokeConfig.hybrid_candidate_limit
        self._configuredProductUrls = list(kurlySmokeConfig.product_urls)
        self._configuredProductUrlSet = {
            self._NormalizeProductUrl(productUrl)
            for productUrl in self._configuredProductUrls
        }
        self._semanticCandidateIndex: Optional[CnSemanticCandidateIndex] = None
        self._semanticCandidateIndexStatus: Optional[Dict[str, Any]] = None
        self._candidateHierarchyViewerItems: List[Dict[str, Any]] = []
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
        self.RunStage5Smoke(runCandidateViewer=True)

    def RunStage5Smoke(
        self,
        *,
        progressCallback: Optional[Callable[[Dict[str, Any]], None]] = None,
        writeSummaryArtifact: Optional[bool] = None,
        runCandidateViewer: bool = False,
    ) -> Dict[str, Any]:
        self._ConfigureLogger()
        if self._runKurlySmokeBeforeOntology:
            self._EmitProgress(
                progressCallback,
                "KurlyMarketSmokePrerequisite",
                "running",
                "KurlyMarket 수집 smoke 실행",
            )
            self._RunKurlyMarketSmokePrerequisite()
            self._ConfigureLogger()
            self._EmitProgress(
                progressCallback,
                "KurlyMarketSmokePrerequisite",
                "completed",
                "KurlyMarket 수집 smoke 완료",
            )

        runLogger = self._Logger("Run")
        runLogger.info(
            "온톨로지 smoke를 시작합니다 ontology_root={}",
            self._ontologyRootPath,
        )

        contextBuilder = OntologyContextBuilder(self._ontologyRootPath)

        totalPhaseCount = 2

        self._LogStepHeader(
            1,
            totalPhaseCount,
            "사전 점검: core 문서, 검색 컨텍스트, CSV 리소스",
        )
        self._EmitProgress(
            progressCallback,
            "Stage1DocumentLoad",
            "running",
            "core 문서와 retrieval 문서 로드",
        )
        documentSummary = self._RunDocumentLoadSmoke(contextBuilder)
        self._EmitProgress(
            progressCallback,
            "Stage1DocumentLoad",
            "completed",
            "core 문서 로드 완료",
            result=documentSummary,
        )

        queryResults = []
        for queryCase in self._smokeQueries:
            self._EmitProgress(
                progressCallback,
                "Stage2ContextRequest",
                "running",
                "검색 context 생성: {0}".format(queryCase["name"]),
            )
            queryResult = self._RunQuerySmoke(contextBuilder, queryCase)
            queryResults.append(queryResult)
            self._EmitProgress(
                progressCallback,
                "Stage2ContextRequest",
                "completed",
                "검색 context 생성 완료: {0}".format(queryCase["name"]),
                result=queryResult,
            )

        self._EmitProgress(
            progressCallback,
            "Stage3GraphValidation",
            "running",
            "core graph validation",
        )
        validationSummary = self._RunValidationSmoke(contextBuilder)
        self._EmitProgress(
            progressCallback,
            "Stage3GraphValidation",
            "completed",
            "core graph validation 완료",
            result=validationSummary,
        )

        self._EmitProgress(
            progressCallback,
            "Stage4ResourceResolution",
            "running",
            "CSV/resource loadability 확인",
        )
        resourceSummary = self._RunResourceResolutionSmoke(contextBuilder)
        self._EmitProgress(
            progressCallback,
            "Stage4ResourceResolution",
            "completed",
            "CSV/resource loadability 확인 완료",
            result=resourceSummary,
        )

        self._LogStepHeader(
            2,
            totalPhaseCount,
            "정적 로직 + semantic retrieval 후보 생성",
        )
        self._EmitProgress(
            progressCallback,
            "Stage5CandidateRetrieval",
            "running",
            "상품별 CN 후보 생성 및 answer.csv HS6 hit 평가",
        )
        classificationCandidateSummary = self._RunClassificationCandidateSmoke()
        self._EmitProgress(
            progressCallback,
            "Stage5CandidateRetrieval",
            "completed",
            "상품별 CN 후보 생성 완료",
            result=classificationCandidateSummary,
        )

        summary = {
            "run_scope": {
                "mode": "stage5_candidate_retrieval_only",
                "last_executed_stage": "Stage5CandidateRetrieval",
            },
            "ontology_root_path": str(self._ontologyRootPath),
            "document_summary": documentSummary,
            "query_results": queryResults,
            "validation_summary": validationSummary,
            "resource_summary": resourceSummary,
            "classification_candidate_summary": classificationCandidateSummary,
        }
        self._LogSummary(summary)
        shouldWriteSummaryArtifact = (
            self._writeSummaryArtifact
            if writeSummaryArtifact is None
            else writeSummaryArtifact
        )
        if shouldWriteSummaryArtifact:
            self._WriteSummaryArtifact(summary)
        if runCandidateViewer:
            self._RunCandidateHierarchyViewerIfAvailable()
        return summary

    def GetCandidateHierarchyViewerItems(self) -> List[Dict[str, Any]]:
        return [dict(viewerItem) for viewerItem in self._candidateHierarchyViewerItems]

    def _EmitProgress(
        self,
        progressCallback: Optional[Callable[[Dict[str, Any]], None]],
        stage: str,
        status: str,
        message: str,
        **payload: Any,
    ) -> None:
        if progressCallback is None:
            return
        try:
            progressCallback(
                {
                    "stage": stage,
                    "status": status,
                    "message": message,
                    **payload,
                }
            )
        except Exception:
            pass

    def _RunKurlyMarketSmokePrerequisite(self) -> None:
        prerequisiteLogger = self._Logger("KurlyMarketSmokePrerequisite")
        prerequisiteLogger.info(
            (
                "KurlyMarket 수집 smoke를 먼저 실행합니다 url_count={} "
                "summary_artifact={}"
            ),
            len(self._configuredProductUrls),
            self._productSmokeSummaryArtifactPath,
        )
        from kurly_market_smoke import KurlyMarketSmokeRunner

        KurlyMarketSmokeRunner().Run()

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
        inputAdapter = ProductInputAdapter()
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
        selectedSmokeRecords = (
            smokeRecords
            if productLimit is not None and productLimit <= 0
            else smokeRecords[:productLimit]
        )
        preparedProducts: List[Dict[str, Any]] = []
        for smokeRecord in selectedSmokeRecords:
            productInput = inputAdapter.BuildFromData(smokeRecord)
            heuristicCandidates = candidateRetriever.FindCandidates(
                productInput,
                topK=topK,
            )
            if semanticCandidateIndex is not None:
                candidates = candidateRetriever.FindCandidatesWithSemanticIndex(
                    productInput=productInput,
                    semanticIndex=semanticCandidateIndex,
                    heuristicTopK=topK,
                    semanticTopK=self._semanticCandidateTopK,
                    finalCandidateLimit=self._hybridCandidateLimit,
                    minSemanticScore=self._semanticMinScore,
                )
                preLimitCandidates = candidateRetriever.FindCandidatesWithSemanticIndex(
                    productInput=productInput,
                    semanticIndex=semanticCandidateIndex,
                    heuristicTopK=topK,
                    semanticTopK=self._semanticCandidateTopK,
                    finalCandidateLimit=None,
                    minSemanticScore=self._semanticMinScore,
                )
            else:
                candidates = heuristicCandidates
                preLimitCandidates = heuristicCandidates
            preparedProducts.append(
                {
                    "product_page_url": smokeRecord.get("product_page_url"),
                    "product_input": productInput,
                    "heuristic_candidates": heuristicCandidates,
                    "hybrid_pre_limit_candidates": preLimitCandidates,
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

    def _LoadAnswerCodeByProductUrl(self) -> Dict[str, str]:
        if not self._answerCsvPath.exists():
            self._Logger("_LoadAnswerCodeByProductUrl").warning(
                "answer_csv_path={} does not exist",
                self._answerCsvPath,
            )
            return {}

        try:
            answerDataFrame = pd.read_csv(
                self._answerCsvPath,
                dtype=str,
                encoding="utf-8-sig",
                keep_default_na=False,
                index_col=False,
                usecols=[ANSWER_PRODUCT_URL_COLUMN, ANSWER_CODE_COLUMN],
            )
        except Exception as exception:
            self._Logger("_LoadAnswerCodeByProductUrl").warning(
                "answer_csv_path={} read_failed={}",
                self._answerCsvPath,
                exception,
            )
            return {}

        answerCodeByProductUrl: Dict[str, str] = {}
        for _, answerRow in answerDataFrame.iterrows():
            productUrl = self._NormalizeProductUrl(
                str(answerRow.get(ANSWER_PRODUCT_URL_COLUMN, "")),
            )
            answerCode = self._NormalizeAnswerCode(
                str(answerRow.get(ANSWER_CODE_COLUMN, "")),
            )
            if not productUrl or answerCode is None:
                continue
            answerCodeByProductUrl.setdefault(productUrl, answerCode)
        return answerCodeByProductUrl

    def _BuildAnswerEvaluation(
        self,
        productPageUrl: Any,
        expectedAnswerCode: Optional[str],
        candidates: List[CnCandidate],
    ) -> Dict[str, Any]:
        return self._BuildAnswerEvaluationFromCandidateCodeRecords(
            productPageUrl=productPageUrl,
            expectedAnswerCode=expectedAnswerCode,
            candidateCodeRecords=self._BuildCandidateCodeRecords(candidates),
            hitBasis="stage5_final_top5_hs6",
        )

    def _BuildCandidateCodeRecords(
        self,
        candidates: List[CnCandidate],
    ) -> List[Dict[str, Any]]:
        return [
            {
                "rank": candidateIndex,
                "hs8": self._NormalizeCandidateCode(candidate.hs8),
                "hs6": self._NormalizeCandidateCode(
                    candidate.hs6Code or candidate.hs8[:6],
                ),
            }
            for candidateIndex, candidate in enumerate(candidates, start=1)
        ]

    def _BuildRetrievalAnswerDiagnostics(
        self,
        productPageUrl: Any,
        expectedAnswerCode: Optional[str],
        heuristicCandidates: List[CnCandidate],
        preLimitCandidates: List[CnCandidate],
        finalCandidates: List[CnCandidate],
    ) -> Dict[str, Any]:
        heuristicEvaluation = self._BuildAnswerEvaluationFromCandidateCodeRecords(
            productPageUrl=productPageUrl,
            expectedAnswerCode=expectedAnswerCode,
            candidateCodeRecords=self._BuildCandidateCodeRecords(heuristicCandidates),
            hitBasis="stage5_heuristic_hs6",
        )
        preLimitEvaluation = self._BuildAnswerEvaluationFromCandidateCodeRecords(
            productPageUrl=productPageUrl,
            expectedAnswerCode=expectedAnswerCode,
            candidateCodeRecords=self._BuildCandidateCodeRecords(preLimitCandidates),
            hitBasis="stage5_hybrid_pre_limit_hs6",
        )
        finalEvaluation = self._BuildAnswerEvaluationFromCandidateCodeRecords(
            productPageUrl=productPageUrl,
            expectedAnswerCode=expectedAnswerCode,
            candidateCodeRecords=self._BuildCandidateCodeRecords(finalCandidates),
            hitBasis="stage5_final_top5_hs6",
        )
        if expectedAnswerCode is None:
            diagnosis = "missing_answer"
        elif finalEvaluation["is_hit"]:
            diagnosis = "hit_in_final_top5"
        elif preLimitEvaluation["is_hit"]:
            diagnosis = "dropped_by_final_candidate_limit"
        elif heuristicEvaluation["is_hit"]:
            diagnosis = "lost_after_hybrid_merge"
        else:
            diagnosis = "not_found_by_stage5_retrieval"
        return {
            "diagnosis": diagnosis,
            "heuristic": heuristicEvaluation,
            "hybrid_pre_limit": preLimitEvaluation,
            "final_top5": finalEvaluation,
        }

    def _BuildAnswerEvaluationFromCandidateCodeRecords(
        self,
        productPageUrl: Any,
        expectedAnswerCode: Optional[str],
        candidateCodeRecords: List[Dict[str, Any]],
        hitBasis: str,
    ) -> Dict[str, Any]:
        expectedHs6 = (
            expectedAnswerCode[:6]
            if expectedAnswerCode is not None and len(expectedAnswerCode) >= 6
            else None
        )
        normalizedCandidateCodeRecords = [
            {
                **candidateCodeRecord,
                "rank": int(candidateCodeRecord.get("rank", candidateIndex)),
                "hs8": self._NormalizeCandidateCode(
                    candidateCodeRecord.get("hs8"),
                ),
                "hs6": self._NormalizeCandidateCode(
                    candidateCodeRecord.get("hs6"),
                ),
            }
            for candidateIndex, candidateCodeRecord in enumerate(
                candidateCodeRecords,
                start=1,
            )
        ]
        hs6PrefixMatches = [
            candidateCodeRecord
            for candidateCodeRecord in normalizedCandidateCodeRecords
            if expectedHs6 is not None
            and (
                candidateCodeRecord["hs6"] == expectedHs6
                or candidateCodeRecord["hs8"].startswith(expectedHs6)
            )
        ]
        rankedMatches = sorted(
            [
                {**candidateCodeRecord, "match_level": "hs6_prefix"}
                for candidateCodeRecord in hs6PrefixMatches
            ],
            key=lambda candidateCodeRecord: int(candidateCodeRecord["rank"]),
        )
        bestMatch = rankedMatches[0] if rankedMatches else None
        return {
            "product_page_url": productPageUrl,
            "hit_basis": hitBasis,
            "selected_candidate_count": len(normalizedCandidateCodeRecords),
            "expected_code": expectedAnswerCode,
            "expected_hs6": expectedHs6,
            "is_hit": bestMatch is not None,
            "hs6_prefix_hit": len(hs6PrefixMatches) > 0,
            "best_match_rank": (
                bestMatch.get("rank") if bestMatch is not None else None
            ),
            "best_match_hs8": (
                bestMatch.get("hs8") if bestMatch is not None else None
            ),
            "best_match_hs6": (
                bestMatch.get("hs6") if bestMatch is not None else None
            ),
            "best_match_level": (
                bestMatch.get("match_level") if bestMatch is not None else None
            ),
            "candidate_hs8_codes": [
                candidateCodeRecord["hs8"]
                for candidateCodeRecord in normalizedCandidateCodeRecords
            ],
            "candidate_hs6_codes": [
                candidateCodeRecord["hs6"]
                for candidateCodeRecord in normalizedCandidateCodeRecords
            ],
            "candidate_roles": [
                candidateCodeRecord.get("role")
                for candidateCodeRecord in normalizedCandidateCodeRecords
            ],
        }

    def _BuildAnswerEvaluationSummary(
        self,
        productResults: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        evaluatedProductResults = [
            productResult
            for productResult in productResults
            if productResult["answer_evaluation"]["expected_code"] is not None
        ]
        evaluatedProductCount = len(evaluatedProductResults)
        hitCount = sum(
            1
            for productResult in evaluatedProductResults
            if productResult["answer_evaluation"]["is_hit"]
        )
        top1HitCount = sum(
            1
            for productResult in evaluatedProductResults
            if productResult["answer_evaluation"]["best_match_rank"] == 1
        )
        hs6PrefixHitCount = sum(
            1
            for productResult in evaluatedProductResults
            if productResult["answer_evaluation"]["hs6_prefix_hit"]
        )
        hitBasis = "stage5_final_top5_hs6"
        if evaluatedProductResults:
            hitBasis = evaluatedProductResults[0]["answer_evaluation"].get(
                "hit_basis",
                hitBasis,
            )
        return {
            "hit_basis": hitBasis,
            "evaluated_product_count": evaluatedProductCount,
            "hit_count": hitCount,
            "miss_count": evaluatedProductCount - hitCount,
            "top1_hit_count": top1HitCount,
            "hs6_prefix_hit_count": hs6PrefixHitCount,
            "hit_rate": self._BuildRate(hitCount, evaluatedProductCount),
            "top1_hit_rate": self._BuildRate(top1HitCount, evaluatedProductCount),
            "hs6_prefix_hit_rate": self._BuildRate(
                hs6PrefixHitCount,
                evaluatedProductCount,
            ),
        }

    def _BuildMissingProductSmokeUrls(
        self,
        smokeRecords: List[Dict[str, Any]],
    ) -> List[str]:
        if not self._configuredProductUrlSet:
            return []
        smokeRecordUrlSet = {
            self._NormalizeProductUrl(smokeRecord.get("product_page_url"))
            for smokeRecord in smokeRecords
        }
        return [
            productUrl
            for productUrl in self._configuredProductUrls
            if self._NormalizeProductUrl(productUrl) not in smokeRecordUrlSet
        ]

    def _BuildMissingAnswerUrls(
        self,
        answerCodeByProductUrl: Dict[str, str],
    ) -> List[str]:
        if not self._configuredProductUrlSet:
            return []
        return [
            productUrl
            for productUrl in self._configuredProductUrls
            if self._NormalizeProductUrl(productUrl) not in answerCodeByProductUrl
        ]

    @staticmethod
    def _BuildRate(numerator: int, denominator: int) -> Optional[float]:
        if denominator <= 0:
            return None
        return round(numerator / denominator, 4)

    @staticmethod
    def _NormalizeProductUrl(productUrl: Any) -> str:
        if not isinstance(productUrl, str):
            return ""
        return productUrl.strip().rstrip("/")

    @staticmethod
    def _NormalizeAnswerCode(answerCode: Any) -> Optional[str]:
        if not isinstance(answerCode, str):
            return None
        digitCode = "".join(
            character for character in answerCode if character.isdigit()
        )
        if not digitCode:
            return None
        if len(digitCode) == 9:
            return digitCode.zfill(10)
        return digitCode

    @staticmethod
    def _NormalizeCandidateCode(candidateCode: Any) -> str:
        if not isinstance(candidateCode, str):
            return ""
        return "".join(
            character for character in candidateCode if character.isdigit()
        )

    def _RunClassificationCandidateSmoke(self) -> Dict[str, Any]:
        smokeRecords = self._LoadProductSmokeRecords()
        preparedProducts = self._BuildStage1PreparedProducts(
            topK=self._cnCandidateTopK,
        )
        answerCodeByProductUrl = self._LoadAnswerCodeByProductUrl()

        productResults: List[Dict[str, Any]] = []
        candidateHierarchyViewerItems: List[Dict[str, Any]] = []
        for preparedProduct in preparedProducts:
            productPageUrl = preparedProduct.get("product_page_url")
            productInput = preparedProduct["product_input"]
            heuristicCandidates = preparedProduct["heuristic_candidates"]
            preLimitCandidates = preparedProduct["hybrid_pre_limit_candidates"]
            candidates = preparedProduct["candidates"]
            candidateRetrieval = preparedProduct["candidate_retrieval"]
            searchText = productInput.BuildSearchText()
            semanticSearchText = productInput.BuildSemanticSearchText()
            normalizedProductUrl = self._NormalizeProductUrl(productPageUrl)
            expectedAnswerCode = answerCodeByProductUrl.get(normalizedProductUrl)
            answerEvaluation = self._BuildAnswerEvaluation(
                productPageUrl=productPageUrl,
                expectedAnswerCode=expectedAnswerCode,
                candidates=candidates,
            )
            retrievalAnswerDiagnostics = self._BuildRetrievalAnswerDiagnostics(
                productPageUrl=productPageUrl,
                expectedAnswerCode=expectedAnswerCode,
                heuristicCandidates=heuristicCandidates,
                preLimitCandidates=preLimitCandidates,
                finalCandidates=candidates,
            )
            candidateHierarchyViewerItems.append(
                {
                    "product_name": productInput.productName,
                    "product_page_url": productPageUrl,
                    "expected_hs6": answerEvaluation["expected_hs6"],
                    "hit": answerEvaluation["is_hit"],
                    "match_rank": answerEvaluation["best_match_rank"],
                    "diagnosis": retrievalAnswerDiagnostics["diagnosis"],
                    "candidate_hs6_codes": answerEvaluation["candidate_hs6_codes"],
                    "tree": self._BuildCandidateHierarchyTree(
                        "final_top5",
                        candidates,
                    ),
                }
            )
            productResults.append(
                {
                    "product_page_url": productPageUrl,
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
                    "retrieval_answer_diagnostics": retrievalAnswerDiagnostics,
                    "heuristic_candidate_count": len(heuristicCandidates),
                    "hybrid_pre_limit_candidate_count": len(preLimitCandidates),
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
                    "answer_evaluation": answerEvaluation,
                    "heuristic_candidate_codes": [
                        candidate.hs8 for candidate in heuristicCandidates
                    ],
                    "hybrid_pre_limit_candidate_codes": [
                        candidate.hs8 for candidate in preLimitCandidates
                    ],
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
            "configured_product_url_count": len(self._configuredProductUrls),
            "answer_csv_path": str(self._answerCsvPath),
            "answer_record_count": len(answerCodeByProductUrl),
            "missing_product_smoke_urls": self._BuildMissingProductSmokeUrls(
                smokeRecords,
            ),
            "missing_answer_urls": self._BuildMissingAnswerUrls(
                answerCodeByProductUrl,
            ),
            "product_smoke_record_count": len(smokeRecords),
            "used_product_count": len(productResults),
            "candidate_top_k": self._cnCandidateTopK,
            "semantic_candidate_top_k": self._semanticCandidateTopK,
            "hybrid_candidate_limit": self._hybridCandidateLimit,
            "semantic_index_status": dict(self._semanticCandidateIndexStatus or {}),
            "answer_evaluation_summary": self._BuildAnswerEvaluationSummary(
                productResults,
            ),
            "products": productResults,
        }
        self._candidateHierarchyViewerItems = candidateHierarchyViewerItems
        self._LogCandidateScoring(result)
        return result

    def _LogCandidateScoring(self, result: Dict[str, Any]) -> None:
        candidateLogger = self._Logger("Stage5CandidateRetrieval")
        candidateLogger.info(
            (
                "candidate_generation products={}/{} heuristic_top_k={} "
                "semantic_top_k={} final_limit={} semantic_status={}"
            ),
            result["used_product_count"],
            result["product_smoke_record_count"],
            result["candidate_top_k"],
            result["semantic_candidate_top_k"],
            result["hybrid_candidate_limit"],
            result["semantic_index_status"].get("status", "not_attempted"),
        )
        self._LogAnswerEvaluation(
            result,
            functionName="Stage5AnswerEvaluation",
            includeDetails=False,
        )
        answerEvaluationSummary = result["answer_evaluation_summary"]
        candidateLogger.info(
            (
                "candidate_answer_check basis={} evaluated={} hit={} miss={} "
                "top1_hit={} hit_rate={} missing_artifact={} missing_answer={}"
            ),
            answerEvaluationSummary["hit_basis"],
            answerEvaluationSummary["evaluated_product_count"],
            answerEvaluationSummary["hit_count"],
            answerEvaluationSummary["miss_count"],
            answerEvaluationSummary["top1_hit_count"],
            answerEvaluationSummary["hit_rate"],
            len(result["missing_product_smoke_urls"]),
            len(result["missing_answer_urls"]),
        )
        candidateLogger.info(
            (
                "retrieval_policy domain_filter=true static_and_semantic_merged=true "
                "semantic_top_k={} final_candidate_limit={}"
            ),
            result["semantic_candidate_top_k"],
            result["hybrid_candidate_limit"],
        )
        for productResult in result["products"]:
            productInput = productResult["product_input"]
            candidateRetrieval = productResult["candidate_retrieval"]
            answerEvaluation = productResult["answer_evaluation"]
            retrievalDiagnostics = productResult["retrieval_answer_diagnostics"]
            candidateCodes = [
                candidate["hs8"]
                for candidate in productResult["candidate_scores"]
            ]
            candidateLogger.info(
                (
                    "product={} domain={} mode={} candidates={} "
                    "expected_hs6={} hit={} match_rank={} diagnosis={} "
                    "heuristic_rank={} prelimit_rank={} final_rank={}"
                ),
                productInput["product_name"],
                productInput["product_domain"],
                candidateRetrieval["mode"],
                candidateCodes,
                answerEvaluation["expected_hs6"],
                answerEvaluation["is_hit"],
                answerEvaluation["best_match_rank"],
                retrievalDiagnostics["diagnosis"],
                retrievalDiagnostics["heuristic"]["best_match_rank"],
                retrievalDiagnostics["hybrid_pre_limit"]["best_match_rank"],
                retrievalDiagnostics["final_top5"]["best_match_rank"],
            )

    def _LogAnswerEvaluation(
        self,
        result: Dict[str, Any],
        functionName: str,
        includeDetails: bool,
    ) -> None:
        answerLogger = self._Logger(functionName)
        answerEvaluationSummary = result.get("answer_evaluation_summary", {})
        if not isinstance(answerEvaluationSummary, dict):
            answerLogger.warning("ANSWER_EVALUATION missing_summary=true")
            return

        missingProductSmokeUrls = result.get("missing_product_smoke_urls", [])
        missingAnswerUrls = result.get("missing_answer_urls", [])
        products = result.get("products", [])
        if not isinstance(products, list):
            products = []

        answerLogger.info(
            (
                "ANSWER_EVALUATION summary basis={} answer_records={} evaluated={} "
                "hit={} miss={} top1_hit={} hit_rate={} top1_hit_rate={} "
                "missing_artifact={} missing_answer={}"
            ),
            answerEvaluationSummary.get(
                "hit_basis",
                "selected_candidate_set_hs6",
            ),
            result.get("answer_record_count"),
            answerEvaluationSummary.get("evaluated_product_count"),
            answerEvaluationSummary.get("hit_count"),
            answerEvaluationSummary.get("miss_count"),
            answerEvaluationSummary.get("top1_hit_count"),
            answerEvaluationSummary.get("hit_rate"),
            answerEvaluationSummary.get("top1_hit_rate"),
            len(missingProductSmokeUrls) if isinstance(missingProductSmokeUrls, list) else 0,
            len(missingAnswerUrls) if isinstance(missingAnswerUrls, list) else 0,
        )

        if not includeDetails:
            return

        hitProducts = [
            productResult
            for productResult in products
            if productResult.get("answer_evaluation", {}).get("is_hit")
        ]
        missProducts = [
            productResult
            for productResult in products
            if productResult.get("answer_evaluation", {}).get("expected_code")
            and not productResult.get("answer_evaluation", {}).get("is_hit")
        ]

        if not hitProducts:
            answerLogger.warning("ANSWER_EVALUATION hit_count=0")
        for productResult in hitProducts:
            productInput = productResult.get("product_input", {})
            answerEvaluation = productResult.get("answer_evaluation", {})
            selectedCandidateCount = answerEvaluation.get(
                "selected_candidate_count",
                len(answerEvaluation.get("candidate_hs8_codes", [])),
            )
            answerLogger.info(
                (
                    "ANSWER_EVALUATION hit product={} expected_code={} "
                    "expected_hs6={} matched_hs8={} matched_hs6={} "
                    "match_rank={} selected_candidate_count={} url={}"
                ),
                productInput.get("product_name"),
                answerEvaluation.get("expected_code"),
                answerEvaluation.get("expected_hs6"),
                answerEvaluation.get("best_match_hs8"),
                answerEvaluation.get("best_match_hs6"),
                answerEvaluation.get("best_match_rank"),
                selectedCandidateCount,
                answerEvaluation.get("product_page_url"),
            )

        previewMissProducts = missProducts[:ANSWER_EVALUATION_LOG_PREVIEW_COUNT]
        answerLogger.info(
            "ANSWER_EVALUATION miss_preview total={} showing={}",
            len(missProducts),
            len(previewMissProducts),
        )
        for productResult in previewMissProducts:
            productInput = productResult.get("product_input", {})
            answerEvaluation = productResult.get("answer_evaluation", {})
            selectedCandidateCount = answerEvaluation.get(
                "selected_candidate_count",
                len(answerEvaluation.get("candidate_hs8_codes", [])),
            )
            answerLogger.info(
                (
                    "ANSWER_EVALUATION miss product={} expected_code={} "
                    "expected_hs6={} selected_candidate_count={} "
                    "candidate_hs6={} url={}"
                ),
                productInput.get("product_name"),
                answerEvaluation.get("expected_code"),
                answerEvaluation.get("expected_hs6"),
                selectedCandidateCount,
                answerEvaluation.get("candidate_hs6_codes"),
                answerEvaluation.get("product_page_url"),
            )

    def _LogSummary(self, summary: Dict[str, Any]) -> None:
        summaryLogger = self._Logger("_LogSummary")
        successfulQueryCount = sum(
            1
            for queryResult in summary["query_results"]
            if queryResult["status"]["has_context"]
        )
        candidateEvaluationSummary = summary["classification_candidate_summary"][
            "answer_evaluation_summary"
        ]
        summaryLogger.info(
            (
                "\n[Smoke 요약]\n"
                "- 실행 범위: mode={} last_stage={}\n"
                "- 준비: documents={} retrieval_docs={} query_context={}/{} "
                "validation={} errors={} warnings={} resources={}/{}\n"
                "- 정적/semantic 후보: products={} hit={}/{} top1_hit={} "
                "hit_rate={}"
            ),
            summary["run_scope"]["mode"],
            summary["run_scope"]["last_executed_stage"],
            summary["document_summary"]["document_count"],
            summary["document_summary"]["retrieval_document_count"],
            successfulQueryCount,
            len(summary["query_results"]),
            summary["validation_summary"]["is_valid"],
            summary["validation_summary"]["error_count"],
            summary["validation_summary"]["warning_count"],
            summary["resource_summary"]["loadable_count"],
            summary["resource_summary"]["total_count"],
            summary["classification_candidate_summary"]["used_product_count"],
            candidateEvaluationSummary["hit_count"],
            candidateEvaluationSummary["evaluated_product_count"],
            candidateEvaluationSummary["top1_hit_count"],
            candidateEvaluationSummary["hit_rate"],
        )

    def _LogStepHeader(self, stepIndex: int, totalStepCount: int, title: str) -> None:
        self._Logger("Run").info(
            "\n\n========== PHASE {}/{} ==========\n{}\n==============================",
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
        if not self._configuredProductUrlSet:
            return productSmokeRecords

        productSmokeRecordByUrl = {
            self._NormalizeProductUrl(productSmokeRecord.get("product_page_url")): (
                productSmokeRecord
            )
            for productSmokeRecord in productSmokeRecords
        }
        filteredProductSmokeRecords: List[Dict[str, Any]] = []
        for configuredProductUrl in self._configuredProductUrls:
            normalizedProductUrl = self._NormalizeProductUrl(configuredProductUrl)
            productSmokeRecord = productSmokeRecordByUrl.get(normalizedProductUrl)
            if productSmokeRecord is not None:
                filteredProductSmokeRecords.append(productSmokeRecord)
        return filteredProductSmokeRecords

    def _BuildTextPreview(self, text: str) -> str:
        if len(text) <= self._textPreviewCharacters:
            return text
        return f"{text[:self._textPreviewCharacters]}..."

    def _BuildCandidateHierarchyTree(
        self,
        title: str,
        candidates: List[CnCandidate],
    ) -> str:
        if not candidates:
            return "{0} candidate_hierarchy count=0".format(title)

        lines = [
            "{0} candidate_hierarchy count={1}".format(
                title,
                len(candidates),
            )
        ]
        rankedCandidates = [
            (rank, candidate)
            for rank, candidate in enumerate(candidates, start=1)
        ]
        hs2Groups = self._GroupRankedCandidatesByKey(
            rankedCandidates,
            lambda rankedCandidate: rankedCandidate[1].hs2Code or "unknown",
        )
        for hs2Index, (hs2Code, hs2Candidates) in enumerate(hs2Groups.items()):
            hs2Representative = hs2Candidates[0][1]
            hs2Prefix = self._BuildTreeBranchPrefix(
                hs2Index,
                len(hs2Groups),
            )
            lines.append(
                "{0}HS2 {1}: {2}".format(
                    hs2Prefix,
                    hs2Code,
                    self._FormatTreeDescription(
                        hs2Representative.hs2Description,
                    ),
                )
            )
            hs4Groups = self._GroupRankedCandidatesByKey(
                hs2Candidates,
                lambda rankedCandidate: rankedCandidate[1].hs4Code or "unknown",
            )
            hs2ChildIndent = self._BuildTreeChildIndent(
                hs2Index,
                len(hs2Groups),
            )
            for hs4Index, (hs4Code, hs4Candidates) in enumerate(hs4Groups.items()):
                hs4Representative = hs4Candidates[0][1]
                hs4Prefix = hs2ChildIndent + self._BuildTreeBranchPrefix(
                    hs4Index,
                    len(hs4Groups),
                )
                lines.append(
                    "{0}HS4 {1}: {2}".format(
                        hs4Prefix,
                        hs4Code,
                        self._FormatTreeDescription(
                            hs4Representative.hs4Description,
                        ),
                    )
                )
                hs6Groups = self._GroupRankedCandidatesByKey(
                    hs4Candidates,
                    lambda rankedCandidate: rankedCandidate[1].hs6Code or "unknown",
                )
                hs4ChildIndent = hs2ChildIndent + self._BuildTreeChildIndent(
                    hs4Index,
                    len(hs4Groups),
                )
                for hs6Index, (hs6Code, hs6Candidates) in enumerate(hs6Groups.items()):
                    hs6Representative = hs6Candidates[0][1]
                    hs6Prefix = hs4ChildIndent + self._BuildTreeBranchPrefix(
                        hs6Index,
                        len(hs6Groups),
                    )
                    lines.append(
                        "{0}HS6 {1}: {2}".format(
                            hs6Prefix,
                            hs6Code,
                            self._FormatTreeDescription(
                                hs6Representative.hs6Description,
                            ),
                        )
                    )
                    hs6ChildIndent = hs4ChildIndent + self._BuildTreeChildIndent(
                        hs6Index,
                        len(hs6Groups),
                    )
                    for candidateIndex, rankedCandidate in enumerate(hs6Candidates):
                        rank, candidate = rankedCandidate
                        candidatePrefix = hs6ChildIndent + self._BuildTreeBranchPrefix(
                            candidateIndex,
                            len(hs6Candidates),
                        )
                        scoreIndent = hs6ChildIndent + self._BuildTreeChildIndent(
                            candidateIndex,
                            len(hs6Candidates),
                        )
                        lines.extend(
                            self._BuildCandidateTreeLines(
                                candidatePrefix,
                                scoreIndent,
                                rank,
                                candidate,
                            )
                        )
        return "\n".join(lines)

    def _BuildCandidateTreeLines(
        self,
        candidatePrefix: str,
        scoreIndent: str,
        rank: int,
        candidate: CnCandidate,
    ) -> List[str]:
        scoreBreakdown = candidate.scoreBreakdown
        semanticScore = (
            "-"
            if candidate.semanticScore is None
            else "{0:.4f}".format(candidate.semanticScore)
        )
        retrievalSources = ",".join(candidate.retrievalSources) or "-"
        lines = [
            "{0}CN8 {1}: {2}".format(
                candidatePrefix,
                candidate.hs8,
                self._FormatTreeDescription(candidate.hs8Description),
            ),
            (
                "{0}score rank={1} total={2:.3f} semantic={3} "
                "sources={4}"
            ).format(
                scoreIndent,
                rank,
                candidate.score,
                semanticScore,
                retrievalSources,
            ),
            (
                "{0}breakdown include={1} search={2} description={3} "
                "semantic={4}"
            ).format(
                scoreIndent,
                scoreBreakdown.get("include_rule_points"),
                scoreBreakdown.get("search_keyword_points"),
                scoreBreakdown.get("description_points"),
                scoreBreakdown.get("semantic_score"),
            ),
        ]
        hierarchyPointSummary = self._BuildHierarchyPointSummary(
            scoreBreakdown.get("hierarchy_level_points"),
        )
        if hierarchyPointSummary:
            lines.append(
                "{0}hierarchy_points {1}".format(
                    scoreIndent,
                    hierarchyPointSummary,
                )
            )
        hierarchyMatchSummary = self._BuildHierarchyMatchSummary(
            scoreBreakdown.get("hierarchy_level_matches"),
        )
        if hierarchyMatchSummary:
            lines.append(
                "{0}hierarchy_matches {1}".format(
                    scoreIndent,
                    hierarchyMatchSummary,
                )
            )
        matchSummary = self._BuildCandidateMatchSummary(candidate)
        if matchSummary:
            lines.append("{0}matches {1}".format(scoreIndent, matchSummary))
        if candidate.excludeRuleMatches:
            lines.append(
                "{0}exclude={1}".format(
                    scoreIndent,
                    self._FormatMatchList(candidate.excludeRuleMatches),
                )
            )
        return lines

    def _BuildHierarchyPointSummary(self, rawValue: Any) -> str:
        if not isinstance(rawValue, Mapping):
            return ""
        parts: List[str] = []
        for level in ["hs2", "hs4", "hs6", "branch", "cn8", "note"]:
            pointValue = rawValue.get(level)
            if not isinstance(pointValue, (int, float)):
                continue
            parts.append("{0}={1:.3f}".format(level, float(pointValue)))
        return " ".join(parts)

    def _BuildHierarchyMatchSummary(self, rawValue: Any) -> str:
        if not isinstance(rawValue, Mapping):
            return ""
        parts: List[str] = []
        for level in ["hs2", "hs4", "hs6", "branch", "cn8", "note"]:
            levelMatches = rawValue.get(level)
            if not isinstance(levelMatches, list):
                continue
            formattedMatches = self._FormatMatchList(
                [
                    str(match)
                    for match in levelMatches
                    if isinstance(match, str) and match.strip()
                ],
                limit=3,
            )
            if formattedMatches == "-":
                continue
            parts.append("{0}={1}".format(level, formattedMatches))
        return " ".join(parts)

    def _BuildCandidateMatchSummary(self, candidate: CnCandidate) -> str:
        parts: List[str] = []
        primaryMatches = self._FormatMatchList(candidate.primaryEvidenceMatches)
        secondaryMatches = self._FormatMatchList(candidate.secondaryEvidenceMatches)
        weakMatches = self._FormatMatchList(candidate.weakEvidenceMatches)
        if primaryMatches != "-":
            parts.append("primary={0}".format(primaryMatches))
        if secondaryMatches != "-":
            parts.append("secondary={0}".format(secondaryMatches))
        if weakMatches != "-":
            parts.append("weak={0}".format(weakMatches))
        return " ".join(parts)

    def _FormatMatchList(
        self,
        matches: List[str],
        limit: int = 5,
    ) -> str:
        if not matches:
            return "-"
        formattedMatches = [
            self._FormatTreeDescription(match, maxCharacters=28)
            for match in matches[:limit]
        ]
        if len(matches) > limit:
            formattedMatches.append("+{0}".format(len(matches) - limit))
        return "[{0}]".format(", ".join(formattedMatches))

    def _FormatTreeDescription(
        self,
        text: Optional[str],
        maxCharacters: int = 80,
    ) -> str:
        normalizedText = " ".join(str(text or "").split())
        if not normalizedText:
            return "-"
        if len(normalizedText) <= maxCharacters:
            return normalizedText
        return "{0}...".format(normalizedText[:maxCharacters])

    def _GroupRankedCandidatesByKey(
        self,
        rankedCandidates: List[tuple[int, CnCandidate]],
        keyBuilder: Callable[[tuple[int, CnCandidate]], str],
    ) -> Dict[str, List[tuple[int, CnCandidate]]]:
        groupedCandidates: Dict[str, List[tuple[int, CnCandidate]]] = {}
        for rankedCandidate in rankedCandidates:
            groupKey = str(keyBuilder(rankedCandidate))
            groupedCandidates.setdefault(groupKey, []).append(rankedCandidate)
        return groupedCandidates

    @staticmethod
    def _BuildTreeBranchPrefix(index: int, totalCount: int) -> str:
        if index == totalCount - 1:
            return "└── "
        return "├── "

    @staticmethod
    def _BuildTreeChildIndent(index: int, totalCount: int) -> str:
        if index == totalCount - 1:
            return "    "
        return "│   "

    def _RunCandidateHierarchyViewerIfAvailable(self) -> None:
        if not self._candidateHierarchyViewerItems:
            return
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            self._Logger("CandidateTreeViewer").info(
                "candidate_tree_viewer skipped=true reason=not_tty products={}",
                len(self._candidateHierarchyViewerItems),
            )
            return
        self._RunCandidateHierarchyViewer(self._candidateHierarchyViewerItems)

    def _RunCandidateHierarchyViewer(
        self,
        viewerItems: List[Dict[str, Any]],
    ) -> None:
        terminalState = termios.tcgetattr(sys.stdin.fileno())
        try:
            tty.setcbreak(sys.stdin.fileno())
            currentIndex = 0
            while True:
                self._RenderCandidateHierarchyViewerItem(
                    viewerItems,
                    currentIndex,
                )
                keyName = self._ReadTerminalKey()
                if keyName in {"q", "Q", "ctrl_c", "ctrl_d"}:
                    break
                if keyName == "right":
                    currentIndex = (currentIndex + 1) % len(viewerItems)
                    continue
                if keyName == "left":
                    currentIndex = (currentIndex - 1) % len(viewerItems)
                    continue
        except KeyboardInterrupt:
            pass
        finally:
            termios.tcsetattr(
                sys.stdin.fileno(),
                termios.TCSADRAIN,
                terminalState,
            )
            sys.stdout.write("\n")
            sys.stdout.flush()

    def _RenderCandidateHierarchyViewerItem(
        self,
        viewerItems: List[Dict[str, Any]],
        currentIndex: int,
    ) -> None:
        viewerItem = viewerItems[currentIndex]
        terminalSize = shutil.get_terminal_size((120, 40))
        separator = "-" * min(terminalSize.columns, 120)
        productName = self._FormatViewerValue(viewerItem.get("product_name"))
        expectedHs6 = self._FormatViewerValue(viewerItem.get("expected_hs6"))
        matchRank = self._FormatViewerValue(viewerItem.get("match_rank"))
        candidateHs6Codes = viewerItem.get("candidate_hs6_codes", [])
        if not isinstance(candidateHs6Codes, list):
            candidateHs6Codes = []
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write(
            (
                "Candidate Hierarchy Viewer  {0}/{1}\n"
                "←/→: 상품 이동   q: 종료\n"
                "{2}\n"
            ).format(
                currentIndex + 1,
                len(viewerItems),
                separator,
            )
        )
        sys.stdout.write("product: {0}\n".format(productName))
        sys.stdout.write(
            "expected_hs6={0} hit={1} match_rank={2} diagnosis={3}\n".format(
                expectedHs6,
                viewerItem.get("hit"),
                matchRank,
                self._FormatViewerValue(viewerItem.get("diagnosis")),
            )
        )
        sys.stdout.write(
            "candidate_hs6={0}\n".format(
                ", ".join(str(code) for code in candidateHs6Codes) or "-",
            )
        )
        sys.stdout.write("{0}\n".format(separator))
        sys.stdout.write(str(viewerItem.get("tree", "")))
        sys.stdout.write("\n{0}\n".format(separator))
        sys.stdout.flush()

    def _ReadTerminalKey(self) -> str:
        firstCharacter = sys.stdin.read(1)
        if firstCharacter == "\x03":
            return "ctrl_c"
        if firstCharacter == "\x04":
            return "ctrl_d"
        if firstCharacter != "\x1b":
            return firstCharacter

        secondCharacter = sys.stdin.read(1)
        thirdCharacter = sys.stdin.read(1)
        if secondCharacter == "[" and thirdCharacter == "C":
            return "right"
        if secondCharacter == "[" and thirdCharacter == "D":
            return "left"
        return "escape"

    @staticmethod
    def _FormatViewerValue(value: Any) -> str:
        if value is None:
            return "-"
        text = str(value)
        if text.strip() == "":
            return "-"
        return text

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
