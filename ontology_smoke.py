"""Ontology context/request builder runtime smoke.

이 파일은 ontology 관련 smoke를 단계별로 누적하는 단일 진입점이다.
새 smoke 단계가 필요하면 별도 파일을 만들지 말고 이 runner에 단계를 추가한다.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


PROJECT_ROOT_PATH = Path(__file__).resolve().parent
SOURCE_ROOT_PATH = PROJECT_ROOT_PATH / "src"
if str(SOURCE_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT_PATH))

from eu_export.bridge import (  # noqa: E402
    BuildLlmRuntimeConfigFromEnv,
    BuildRuntimeAdapter,
    ProbeRuntimeDependency,
    RuntimeAdapterBuildError,
    RuntimeGenerationError,
)
from eu_export.ontology import (  # noqa: E402
    CnCandidate,
    CnCandidateRetriever,
    DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
    LlmRequestBuilder,
    OntologyContextBuilder,
    OntologyGraphValidator,
    OntologyResourceResolver,
    ProductClassificationInput,
    ProductClassificationInputNormalizer,
    Stage1ClassificationRecommendationReportBuilder,
    Stage1ClassificationResponseValidator,
    Stage1ClassificationRequestBuilder,
    Stage1DecisionPolicy,
    Stage1DecisionReport,
    Stage1EvidencePackage,
    Stage1EvidencePackageBuilder,
    Stage1HumanReviewPackageBuilder,
    Stage1TraversalController,
)
from eu_export.utils import NormalizeWhitespace  # noqa: E402


DEFAULT_ONTOLOGY_ROOT_PATH = PROJECT_ROOT_PATH / "eu_export_ontology_v1"
DEFAULT_ARTIFACT_ROOT_PATH = PROJECT_ROOT_PATH / "artifacts" / "ontology-smoke"
DEFAULT_SUMMARY_ARTIFACT_PATH = DEFAULT_ARTIFACT_ROOT_PATH / "runtime-smoke-summary.json"
DEFAULT_HUMAN_REVIEW_PACKAGE_ARTIFACT_PATH = (
    DEFAULT_ARTIFACT_ROOT_PATH / "stage1-human-review-package.json"
)
DEFAULT_PRODUCT_SMOKE_SUMMARY_ARTIFACT_PATH = (
    PROJECT_ROOT_PATH / "artifacts" / "kurly-market-smoke" / "runtime-smoke-summary.json"
)
DEFAULT_TOP_K = 8
DEFAULT_MAX_RESULT_COUNT = 6
DEFAULT_CN_CANDIDATE_TOP_K = 5
DEFAULT_MAX_PRODUCT_SMOKE_INPUTS = 2
DEFAULT_PHASE_ID = "stage1_classification"
DEFAULT_WRITE_SUMMARY_ARTIFACT = True
DEFAULT_TEXT_PREVIEW_CHARACTERS = 700
DEFAULT_VALIDATION_ISSUE_PREVIEW_COUNT = 3
DEFAULT_RESOURCE_CHECK_PREVIEW_COUNT = 8
DEFAULT_MAX_VALIDATION_FIXTURE_CANDIDATES = 3
DEFAULT_STAGE1_BACKTRACKING_RETRY_ATTEMPT = 0
NO_CN_CANDIDATE_REASON = "no CN candidates found for product input"

DEFAULT_SMOKE_QUERIES = [
    {
        "name": "stage1_cosmetics_classification",
        "phase_id": DEFAULT_PHASE_ID,
        "query": (
            "화장품 HS6 CN8 후보 분류 stage1 classification "
            "cn_leaf_code_cards classification evidence"
        ),
        "user_prompt": "화장품 제품의 HS6/CN8 후보 분류 기준을 설명해줘.",
    },
    {
        "name": "stage1_food_classification",
        "phase_id": DEFAULT_PHASE_ID,
        "query": (
            "식품 HS6 CN8 후보 분류 stage1 classification "
            "food cn_leaf_code_cards domain scope"
        ),
        "user_prompt": "식품 제품의 HS6/CN8 후보 분류 기준을 설명해줘.",
    },
]


def _ReadBooleanSmokeSetting(envName: str, defaultValue: bool) -> bool:
    value = _ReadSmokeSetting(envName)
    if value is None:
        return defaultValue
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ReadSmokeSetting(envName: str) -> str | None:
    envValue = os.environ.get(envName)
    if envValue is not None and envValue.strip() != "":
        return envValue.strip()

    envFilePath = PROJECT_ROOT_PATH / ".env"
    if not envFilePath.exists():
        return None

    for line in envFilePath.read_text(encoding="utf-8").splitlines():
        strippedLine = line.strip()
        if strippedLine == "" or strippedLine.startswith("#"):
            continue
        if strippedLine.startswith("export "):
            strippedLine = strippedLine[len("export ") :].strip()
        if "=" not in strippedLine:
            continue
        key, rawValue = strippedLine.split("=", 1)
        if key.strip() == envName:
            return _NormalizeSmokeSettingValue(rawValue)
    return None


def _NormalizeSmokeSettingValue(rawValue: str) -> str:
    value = rawValue.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


DEFAULT_RUN_LLM_CONNECTION_SMOKE = _ReadBooleanSmokeSetting(
    "EU_EXPORT_ONTOLOGY_SMOKE_RUN_LLM",
    False,
)


class OntologySmokeRunner:
    """ontology 문서 로드, 검색 context, LLM request 생성을 확인한다."""

    def Run(self) -> None:
        self._ConfigureLogger()
        runLogger = self._Logger("Run")
        runLogger.info(
            "온톨로지 smoke를 시작합니다 ontology_root={}",
            DEFAULT_ONTOLOGY_ROOT_PATH,
        )

        contextBuilder = OntologyContextBuilder(DEFAULT_ONTOLOGY_ROOT_PATH)

        runLogger.info("STEP 1/13 온톨로지 마크다운 문서를 로드합니다")
        documentSummary = self._RunDocumentLoadSmoke(contextBuilder)

        runLogger.info("STEP 2/13 문서 검색 결과가 LLM 요청 컨텍스트로 변환되는지 확인합니다")
        queryResults = [
            self._RunQuerySmoke(contextBuilder, queryCase)
            for queryCase in DEFAULT_SMOKE_QUERIES
        ]

        runLogger.info("STEP 3/13 문서 참조 관계와 frontmatter 메타데이터를 검증합니다")
        validationSummary = self._RunValidationSmoke(contextBuilder)

        runLogger.info("STEP 4/13 문서에 선언된 CSV 데이터 경로를 확인합니다")
        resourceSummary = self._RunResourceResolutionSmoke(contextBuilder)

        runLogger.info("STEP 5/13 상품 정보로 CN 후보를 찾고 휴리스틱 점수를 설명합니다")
        classificationCandidateSummary = self._RunClassificationCandidateSmoke()

        runLogger.info("STEP 6/13 후보 검토용 LLM 요청 JSON 구조를 만듭니다")
        classificationRequestSummary = self._RunClassificationRequestSmoke(
            contextBuilder,
        )

        runLogger.info("STEP 7/13 메인 LLM 후보 검토 응답을 생성하고 검증합니다")
        llmResponseValidationSummary = self._RunLlmResponseValidationSmoke(
            contextBuilder,
        )

        runLogger.info("STEP 8/13 후보 판단에 사용할 근거 묶음을 만듭니다")
        evidencePackageSummary = self._RunEvidencePackageSmoke(contextBuilder)

        runLogger.info("STEP 9/13 후보 리뷰 정책을 fixture 시나리오로 검증합니다")
        decisionPolicySummary = self._RunStage1DecisionPolicySmoke(contextBuilder)

        runLogger.info("STEP 10/13 fixture 시나리오의 다음 파이프라인 동작을 확인합니다")
        traversalControllerSummary = self._RunStage1TraversalControllerSmoke(
            decisionPolicySummary,
        )

        runLogger.info("STEP 11/13 백트래킹 예외 경로를 fixture 시나리오로 검증합니다")
        backtrackingRetrySummary = self._RunStage1BacktrackingRetrySmoke(
            contextBuilder,
            decisionPolicySummary,
        )

        runLogger.info("STEP 12/13 선택된 LLM 후보 검토 결과를 후보 산출 요약으로 정리합니다")
        recommendationReportSummary = self._RunStage1RecommendationReportSmoke(
            llmResponseValidationSummary,
            backtrackingRetrySummary,
        )

        runLogger.info("STEP 13/13 선택된 LLM 후보 검토 결과를 검토용 JSON 패키지로 만듭니다")
        humanReviewPackageSummary = self._RunStage1HumanReviewPackageSmoke(
            llmResponseValidationSummary,
            backtrackingRetrySummary,
        )

        summary = {
            "ontology_root_path": str(DEFAULT_ONTOLOGY_ROOT_PATH),
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
        if DEFAULT_WRITE_SUMMARY_ARTIFACT:
            self._WriteSummaryArtifact(summary)

    def _RunDocumentLoadSmoke(
        self,
        contextBuilder: OntologyContextBuilder,
    ) -> Dict[str, Any]:
        documents = contextBuilder.LoadDocuments()
        retrievalDocuments = contextBuilder.LoadRetrievalDocuments(
            phaseId=DEFAULT_PHASE_ID,
        )
        result = {
            "document_count": len(documents),
            "phase_id": DEFAULT_PHASE_ID,
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
            topK=DEFAULT_TOP_K,
            maxResultCount=DEFAULT_MAX_RESULT_COUNT,
        )
        llmRequest = LlmRequestBuilder().BuildRequest(
            userPrompt=queryCase["user_prompt"],
            packagedContext=context,
        )
        contextData = context.ToDict()
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
            DEFAULT_ONTOLOGY_ROOT_PATH,
        ).Validate(documents)
        validationData = validationReport.ToDict()
        issues = list(validationData["issues"])
        result = {
            "is_valid": validationData["is_valid"],
            "error_count": validationData["error_count"],
            "warning_count": validationData["warning_count"],
            "issues": issues,
            "issues_preview": issues[:DEFAULT_VALIDATION_ISSUE_PREVIEW_COUNT],
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
            DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        ).Resolve(documents)
        resourceData = resourceReport.ToDict()
        checks = list(resourceData["data_source_checks"])
        result = {
            "is_valid": resourceData["is_valid"],
            "total_count": resourceData["total_count"],
            "loadable_count": resourceData["loadable_count"],
            "missing_count": resourceData["missing_count"],
            "invalid_count": resourceData["invalid_count"],
            "data_source_checks": checks,
            "checks_preview": checks[:DEFAULT_RESOURCE_CHECK_PREVIEW_COUNT],
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

    def _RunClassificationCandidateSmoke(self) -> Dict[str, Any]:
        smokeRecords = self._LoadProductSmokeRecords()
        normalizer = ProductClassificationInputNormalizer()
        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )

        productResults: List[Dict[str, Any]] = []
        for smokeRecord in smokeRecords[:DEFAULT_MAX_PRODUCT_SMOKE_INPUTS]:
            productInput = normalizer.BuildFromKurlyPipelineResultData(smokeRecord)
            searchText = productInput.BuildSearchText()
            candidates = candidateRetriever.FindCandidates(
                productInput,
                topK=DEFAULT_CN_CANDIDATE_TOP_K,
            )
            productResults.append(
                {
                    "product_input": productInput.ToDict(),
                    "scoring_input": {
                        "domain_scopes": list(productInput.domainScopes),
                        "search_text_length": len(searchText),
                        "search_text_preview": self._BuildTextPreview(searchText),
                    },
                    "candidate_generation_process": {
                        "purpose": "HS6/CN8 후보 산출 과정 설명",
                        "domain_scope_filter": list(productInput.domainScopes),
                        "scoring_rule": {
                            "include_rule_keyword_match": "+4",
                            "search_keyword_match": "+2",
                            "description_token_match": "+1",
                            "exclude_rule_match": "score forced to 0",
                        },
                        "candidate_rows": [
                            {
                                "rank": candidateIndex,
                                "hs8": candidate.hs8,
                                "hs6_code": candidate.hs6Code,
                                "score": candidate.score,
                                "score_breakdown": candidate.ToDict().get(
                                    "score_breakdown",
                                    {},
                                ),
                                "include_rule_matches": list(
                                    candidate.includeRuleMatches,
                                ),
                                "search_keyword_matches": list(
                                    candidate.searchKeywordMatches,
                                ),
                                "description_matches": list(
                                    candidate.descriptionMatches,
                                ),
                                "exclude_rule_matches": list(
                                    candidate.excludeRuleMatches,
                                ),
                            }
                            for candidateIndex, candidate in enumerate(
                                candidates,
                                start=1,
                            )
                        ],
                    },
                    "candidate_count": len(candidates),
                    "candidates": [
                        candidate.ToDict()
                        for candidate in candidates
                    ],
                }
            )

        result = {
            "product_smoke_summary_path": str(
                DEFAULT_PRODUCT_SMOKE_SUMMARY_ARTIFACT_PATH,
            ),
            "product_smoke_record_count": len(smokeRecords),
            "used_product_count": len(productResults),
            "candidate_top_k": DEFAULT_CN_CANDIDATE_TOP_K,
            "products": productResults,
        }
        self._LogCandidateScoring(result)
        return result

    def _LogCandidateScoring(self, result: Dict[str, Any]) -> None:
        candidateLogger = self._Logger("Stage5CandidateRetrieval")
        candidateLogger.info(
            (
                "후보 검색 입력 artifact를 읽었습니다 product_records={} "
                "used_products={} top_k={}"
            ),
            result["product_smoke_record_count"],
            result["used_product_count"],
            result["candidate_top_k"],
        )
        candidateLogger.info(
            (
                "점수 규칙: 먼저 상품 도메인으로 CSV 범위를 제한하고, "
                "include_rule_keywords 매칭은 +4점, search_keywords 매칭은 +2점, "
                "CN 설명문 토큰 매칭은 +1점으로 계산합니다. "
                "exclude_rule_keywords가 매칭되면 해당 행은 후보에서 제외합니다."
            )
        )
        for productResult in result["products"]:
            productInput = productResult["product_input"]
            scoringInput = productResult["scoring_input"]
            candidateCodes = [
                candidate["hs8"]
                for candidate in productResult["candidates"]
            ]
            candidateLogger.info(
                (
                    "후보 검색 대상 상품: product={} domain={} 검색범위={} "
                    "검색텍스트길이={} 상품고시필드={} OCR텍스트길이={} 후보코드={}"
                ),
                productInput["product_name"],
                productInput["product_domain"],
                scoringInput["domain_scopes"],
                scoringInput["search_text_length"],
                len(productInput["notice_field_texts"]),
                productInput["ocr_text_length"],
                candidateCodes,
            )
            candidateLogger.info(
                "검색 텍스트 예시 product={} text={}",
                productInput["product_name"],
                scoringInput["search_text_preview"],
            )
            for candidateIndex, candidate in enumerate(
                productResult["candidates"],
                start=1,
            ):
                scoreBreakdown = candidate["score_breakdown"]
                candidateLogger.info(
                    (
                        "후보 점수 rank={} hs8={} hs6={} score={} "
                        "include(+4)={} search_keyword(+2)={} "
                        "description(+1)={} exclude={} 설명={}"
                    ),
                    candidateIndex,
                    candidate["hs8"],
                    candidate["hs6_code"],
                    candidate["score"],
                    candidate["include_rule_matches"],
                    candidate["search_keyword_matches"],
                    candidate["description_matches"][:8],
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
        smokeRecords = self._LoadProductSmokeRecords()
        normalizer = ProductClassificationInputNormalizer()
        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        requestBuilder = Stage1ClassificationRequestBuilder()

        requestResults: List[Dict[str, Any]] = []
        for smokeRecord in smokeRecords[:DEFAULT_MAX_PRODUCT_SMOKE_INPUTS]:
            productInput = normalizer.BuildFromKurlyPipelineResultData(smokeRecord)
            candidates = candidateRetriever.FindCandidates(
                productInput,
                topK=DEFAULT_CN_CANDIDATE_TOP_K,
            )
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

            ontologyQuery = requestBuilder.BuildOntologyQuery(productInput, candidates)
            packagedContext = contextBuilder.BuildContext(
                query=ontologyQuery,
                phaseId=DEFAULT_PHASE_ID,
                topK=DEFAULT_TOP_K,
                maxResultCount=DEFAULT_MAX_RESULT_COUNT,
            )
            evidencePackage = evidencePackageBuilder.Build(
                productInput=productInput,
                candidates=candidates,
                packagedContext=packagedContext,
            )
            llmRequest = requestBuilder.BuildRequest(
                productInput=productInput,
                candidates=candidates,
                packagedContext=packagedContext,
                evidencePackage=evidencePackage,
                maxCandidateCount=DEFAULT_CN_CANDIDATE_TOP_K,
            )
            evidenceData = evidencePackage.ToDict()
            promptEvidenceData = evidencePackage.ToPromptDict(
                candidateCodes=[
                    candidate.hs8
                    for candidate in candidates[:DEFAULT_CN_CANDIDATE_TOP_K]
                ],
            )
            requestResults.append(
                {
                    "status": "completed",
                    "product_name": productInput.productName,
                    "product_domain": productInput.productDomain,
                    "candidate_count": len(candidates),
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
                            llmRequest.generationOptions.ToDict()
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
                    "product={} domain={} candidates={} "
                    "response_format={} context_chunks={} ontology_chunks={} "
                    "evidence_records={}"
                ),
                requestResult["product_name"],
                requestResult["product_domain"],
                requestResult["candidate_count"],
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
        smokeRecords = self._LoadProductSmokeRecords()
        normalizer = ProductClassificationInputNormalizer()
        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        requestBuilder = Stage1ClassificationRequestBuilder()

        productResults: List[Dict[str, Any]] = []
        for smokeRecord in smokeRecords[:DEFAULT_MAX_PRODUCT_SMOKE_INPUTS]:
            productInput = normalizer.BuildFromKurlyPipelineResultData(smokeRecord)
            candidates = candidateRetriever.FindCandidates(
                productInput,
                topK=DEFAULT_CN_CANDIDATE_TOP_K,
            )
            ontologyQuery = requestBuilder.BuildOntologyQuery(productInput, candidates)
            packagedContext = contextBuilder.BuildContext(
                query=ontologyQuery,
                phaseId=DEFAULT_PHASE_ID,
                topK=DEFAULT_TOP_K,
                maxResultCount=DEFAULT_MAX_RESULT_COUNT,
            )
            evidencePackage = evidencePackageBuilder.Build(
                productInput=productInput,
                candidates=candidates,
                packagedContext=packagedContext,
            )
            evidenceData = evidencePackage.ToDict()
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
        smokeRecords = self._LoadProductSmokeRecords()
        validator = Stage1ClassificationResponseValidator()

        if not smokeRecords:
            result = {
                "status": "skipped",
                "reason": "product smoke artifact is empty",
                "llm_connection_enabled": DEFAULT_RUN_LLM_CONNECTION_SMOKE,
            }
            self._Logger("Stage7ResponseValidation").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        normalizer = ProductClassificationInputNormalizer()
        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        requestBuilder = Stage1ClassificationRequestBuilder()
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )

        productInput = normalizer.BuildFromKurlyPipelineResultData(smokeRecords[0])
        candidates = candidateRetriever.FindCandidates(
            productInput,
            topK=DEFAULT_MAX_VALIDATION_FIXTURE_CANDIDATES,
        )
        if not candidates:
            result = {
                "status": "skipped",
                "reason": NO_CN_CANDIDATE_REASON,
                "product_name": productInput.productName,
                "candidate_count": 0,
                "llm_connection_enabled": DEFAULT_RUN_LLM_CONNECTION_SMOKE,
            }
            self._Logger("Stage7ResponseValidation").warning(
                "status=skipped product={} reason={}",
                result["product_name"],
                result["reason"],
            )
            return result

        ontologyQuery = requestBuilder.BuildOntologyQuery(productInput, candidates)
        packagedContext = contextBuilder.BuildContext(
            query=ontologyQuery,
            phaseId=DEFAULT_PHASE_ID,
            topK=DEFAULT_TOP_K,
            maxResultCount=DEFAULT_MAX_RESULT_COUNT,
        )
        evidencePackage = evidencePackageBuilder.Build(
            productInput=productInput,
            candidates=candidates,
            packagedContext=packagedContext,
        )
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
            "fixture_validation": fixtureReport.ToDict(),
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
        smokeRecords = self._LoadProductSmokeRecords()
        if not smokeRecords:
            result = {
                "status": "skipped",
                "reason": "product smoke artifact is empty",
            }
            self._Logger("Stage9DecisionPolicy").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        normalizer = ProductClassificationInputNormalizer()
        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        requestBuilder = Stage1ClassificationRequestBuilder()
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        validator = Stage1ClassificationResponseValidator()
        decisionPolicy = Stage1DecisionPolicy()

        productInput = normalizer.BuildFromKurlyPipelineResultData(smokeRecords[0])
        candidates = candidateRetriever.FindCandidates(
            productInput,
            topK=DEFAULT_MAX_VALIDATION_FIXTURE_CANDIDATES,
        )
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

        ontologyQuery = requestBuilder.BuildOntologyQuery(productInput, candidates)
        packagedContext = contextBuilder.BuildContext(
            query=ontologyQuery,
            phaseId=DEFAULT_PHASE_ID,
            topK=DEFAULT_TOP_K,
            maxResultCount=DEFAULT_MAX_RESULT_COUNT,
        )
        evidencePackage = evidencePackageBuilder.Build(
            productInput=productInput,
            candidates=candidates,
            packagedContext=packagedContext,
        )
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
            "possible_fixture_decision": possibleDecisionReport.ToDict(),
            "backtracking_fixture_decision": backtrackingDecisionReport.ToDict(),
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

        smokeRecords = self._LoadProductSmokeRecords()
        if not smokeRecords:
            result = {
                "status": "skipped",
                "reason": "product smoke artifact is empty",
            }
            self._Logger("Stage10TraversalController").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        normalizer = ProductClassificationInputNormalizer()
        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        productInput = normalizer.BuildFromKurlyPipelineResultData(smokeRecords[0])
        candidates = candidateRetriever.FindCandidates(
            productInput,
            topK=DEFAULT_MAX_VALIDATION_FIXTURE_CANDIDATES,
        )
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
            topK=DEFAULT_MAX_VALIDATION_FIXTURE_CANDIDATES,
        )
        result = {
            "status": "completed",
            "scenario_kind": "policy_fixture_traversal",
            "is_main_flow": False,
            "possible_fixture_traversal": possibleTraversalReport.ToDict(),
            "backtracking_fixture_traversal": backtrackingTraversalReport.ToDict(),
            "backtracking_candidate_count": len(backtrackingCandidates),
            "backtracking_candidate_codes": [
                candidate.hs8 for candidate in backtrackingCandidates
            ],
            "backtracking_candidate_preview": [
                candidate.ToDict() for candidate in backtrackingCandidates[:3]
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

        smokeRecords = self._LoadProductSmokeRecords()
        if not smokeRecords:
            result = {
                "status": "skipped",
                "reason": "product smoke artifact is empty",
            }
            self._Logger("Stage11BacktrackingRetry").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        normalizer = ProductClassificationInputNormalizer()
        candidateRetriever = CnCandidateRetriever(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        requestBuilder = Stage1ClassificationRequestBuilder()
        evidencePackageBuilder = Stage1EvidencePackageBuilder(
            ontologyRootPath=DEFAULT_ONTOLOGY_ROOT_PATH,
            projectRootPath=PROJECT_ROOT_PATH,
        )
        productInput = normalizer.BuildFromKurlyPipelineResultData(smokeRecords[0])
        currentCandidates = candidateRetriever.FindCandidates(
            productInput,
            topK=DEFAULT_MAX_VALIDATION_FIXTURE_CANDIDATES,
        )
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
            topK=DEFAULT_MAX_VALIDATION_FIXTURE_CANDIDATES,
            visitedHs8Codes=currentCandidateCodes,
            completedRetryCount=DEFAULT_STAGE1_BACKTRACKING_RETRY_ATTEMPT,
            maxRetryCount=DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
        )
        if not backtrackingCandidates:
            result = {
                "status": "skipped",
                "reason": "backtracking candidate set is empty",
            }
            self._Logger("Stage11BacktrackingRetry").warning(
                "status=skipped reason={}",
                result["reason"],
            )
            return result

        retryCandidateCodes = [candidate.hs8 for candidate in backtrackingCandidates]
        visitedCandidateCodes = [*currentCandidateCodes, *retryCandidateCodes]
        ontologyQuery = requestBuilder.BuildOntologyQuery(
            productInput,
            backtrackingCandidates,
        )
        packagedContext = contextBuilder.BuildContext(
            query=ontologyQuery,
            phaseId=DEFAULT_PHASE_ID,
            topK=DEFAULT_TOP_K,
            maxResultCount=DEFAULT_MAX_RESULT_COUNT,
        )
        evidencePackage = evidencePackageBuilder.Build(
            productInput=productInput,
            candidates=backtrackingCandidates,
            packagedContext=packagedContext,
        )
        backtrackingSummary = {
            "initial_candidate_hs8_codes": currentCandidateCodes,
            "retry_candidate_hs8_codes": retryCandidateCodes,
            "visited_candidate_hs8_codes": visitedCandidateCodes,
            "max_retry_count": DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
            "completed_retry_count": DEFAULT_STAGE1_BACKTRACKING_RETRY_ATTEMPT + 1,
        }
        llmConnectionResult = self._RunOptionalLlmConnectionSmoke(
            contextBuilder=contextBuilder,
            productInput=productInput,
            candidates=backtrackingCandidates,
            requestBuilder=requestBuilder,
            validator=Stage1ClassificationResponseValidator(),
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
                    topK=DEFAULT_MAX_VALIDATION_FIXTURE_CANDIDATES,
                    visitedHs8Codes=visitedCandidateCodes,
                    completedRetryCount=(
                        DEFAULT_STAGE1_BACKTRACKING_RETRY_ATTEMPT + 1
                    ),
                    maxRetryCount=DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
                )
                nextRetryCandidateCodes = [
                    candidate.hs8 for candidate in nextRetryCandidates
                ]
                nextRetryStopReason = (
                    "max_retry_count_reached"
                    if (
                        DEFAULT_STAGE1_BACKTRACKING_RETRY_ATTEMPT + 1
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
            "completed_retry_count": DEFAULT_STAGE1_BACKTRACKING_RETRY_ATTEMPT + 1,
            "visited_candidate_codes": visitedCandidateCodes,
            "retry_candidate_count": len(backtrackingCandidates),
            "retry_candidate_codes": retryCandidateCodes,
            "next_retry_candidate_codes": nextRetryCandidateCodes,
            "next_retry_stop_reason": nextRetryStopReason,
            "evidence_record_count": len(evidencePackage.evidenceRecords),
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
        selectedSource = "stage7_initial_llm_review"
        selectedLlmConnection = llmResponseValidationSummary.get(
            "llm_connection",
            {},
        )
        retryLlmConnection = backtrackingRetrySummary.get(
            "llm_connection",
            {},
        )
        if retryLlmConnection.get("status") == "completed":
            retryScenarioKind = backtrackingRetrySummary.get("scenario_kind")
            if retryScenarioKind == "actual_backtracking_inference":
                selectedSource = "stage11_backtracking_retry"
                selectedLlmConnection = retryLlmConnection

        selectedValidation = selectedLlmConnection.get("validation", {})
        if (
            isinstance(selectedValidation, dict)
            and "is_valid" in selectedValidation
            and selectedValidation.get("is_valid") is not True
        ):
            result = {
                "status": "skipped",
                "reason": "selected llm response is invalid",
                "selected_source": selectedSource,
                "upstream_llm_status": selectedLlmConnection.get("status"),
                "validation_error_count": selectedValidation.get("error_count"),
                "validation_warning_count": selectedValidation.get("warning_count"),
                "validation_issues": selectedValidation.get("issues", []),
            }
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
        selectedSource = "stage7_initial_llm_review"
        selectedLlmConnection = llmResponseValidationSummary.get(
            "llm_connection",
            {},
        )
        retryLlmConnection = backtrackingRetrySummary.get(
            "llm_connection",
            {},
        )
        if retryLlmConnection.get("status") == "completed":
            retryScenarioKind = backtrackingRetrySummary.get("scenario_kind")
            if retryScenarioKind == "actual_backtracking_inference":
                selectedSource = "stage11_backtracking_retry"
                selectedLlmConnection = retryLlmConnection

        selectedValidation = selectedLlmConnection.get("validation", {})
        if (
            isinstance(selectedValidation, dict)
            and "is_valid" in selectedValidation
            and selectedValidation.get("is_valid") is not True
        ):
            result = {
                "status": "skipped",
                "reason": "selected llm response is invalid",
                "selected_source": selectedSource,
                "upstream_llm_status": selectedLlmConnection.get("status"),
                "validation_error_count": selectedValidation.get("error_count"),
                "validation_warning_count": selectedValidation.get("warning_count"),
                "validation_issues": selectedValidation.get("issues", []),
            }
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

        DEFAULT_HUMAN_REVIEW_PACKAGE_ARTIFACT_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        DEFAULT_HUMAN_REVIEW_PACKAGE_ARTIFACT_PATH.write_text(
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
            "package_artifact_path": str(DEFAULT_HUMAN_REVIEW_PACKAGE_ARTIFACT_PATH),
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
        requestBuilder: Stage1ClassificationRequestBuilder,
        validator: Stage1ClassificationResponseValidator,
        evidencePackage: Stage1EvidencePackage,
        backtrackingSummary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not candidates:
            return {
                "enabled": DEFAULT_RUN_LLM_CONNECTION_SMOKE,
                "status": "skipped",
                "reason": NO_CN_CANDIDATE_REASON,
            }

        runtimeConfig = BuildLlmRuntimeConfigFromEnv(
            envFilePath=PROJECT_ROOT_PATH / ".env",
        )
        dependencyStatus = ProbeRuntimeDependency(runtimeConfig)
        baseResult = {
            "enabled": DEFAULT_RUN_LLM_CONNECTION_SMOKE,
            "runtime_kind": runtimeConfig.runtimeKind.value,
            "model_name": runtimeConfig.modelName,
            "endpoint_url": runtimeConfig.endpointUrl,
            "dependency_available": dependencyStatus.isAvailable,
            "dependency_message": dependencyStatus.message,
            "dependency_limitations": list(dependencyStatus.limitations),
        }

        if not DEFAULT_RUN_LLM_CONNECTION_SMOKE:
            return {
                **baseResult,
                "status": "skipped",
                "reason": (
                    "Set EU_EXPORT_ONTOLOGY_SMOKE_RUN_LLM=true to call the "
                    "configured LLM runtime."
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
            ontologyQuery = requestBuilder.BuildOntologyQuery(
                productInput,
                candidates,
            )
            packagedContext = contextBuilder.BuildContext(
                query=ontologyQuery,
                phaseId=DEFAULT_PHASE_ID,
                topK=DEFAULT_TOP_K,
                maxResultCount=DEFAULT_MAX_RESULT_COUNT,
            )
            llmRequest = requestBuilder.BuildRequest(
                productInput=productInput,
                candidates=candidates,
                packagedContext=packagedContext,
                evidencePackage=evidencePackage,
                maxCandidateCount=len(candidates),
            )
            llmResponse = adapter.Generate(llmRequest)
            validationReport = validator.ValidateResponse(
                llmResponse,
                productInput,
                candidates,
                evidencePackage=evidencePackage,
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
                Stage1ClassificationRecommendationReportBuilder().Build(
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
                validationReportData=validationReport.ToDict(),
                decisionReportData=decisionReport.ToDict(),
                traversalReportData=traversalReport.ToDict(),
            )
        except (RuntimeAdapterBuildError, RuntimeGenerationError) as error:
            return {
                **baseResult,
                "status": "failed",
                "error": str(error),
            }

        return {
            **baseResult,
            "status": "completed",
            "response": {
                "generated_text_length": len(llmResponse.generatedText),
                "generated_text_preview": self._BuildTextPreview(
                    llmResponse.generatedText,
                ),
                "runtime_kind": llmResponse.runtimeKind.value,
                "model_name": llmResponse.modelName,
                "response_format": llmResponse.responseFormat.value,
                "finish_reason": llmResponse.finishReason.value,
                "provider_finish_reason": llmResponse.providerFinishReason,
                "token_usage": llmResponse.tokenUsage.ToDict(),
                "limitations": list(llmResponse.limitations),
            },
            "validation": validationReport.ToDict(),
            "decision": decisionReport.ToDict(),
            "traversal": traversalReport.ToDict(),
            "recommendation": recommendationReport.ToDict(),
            "human_review_package": humanReviewPackage.ToDict(),
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
            candidateData = candidate.ToDict()
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

    def _WriteSummaryArtifact(self, summary: Dict[str, Any]) -> None:
        DEFAULT_SUMMARY_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_SUMMARY_ARTIFACT_PATH.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._Logger("_WriteSummaryArtifact").info(
            "summary_artifact_path={}",
            DEFAULT_SUMMARY_ARTIFACT_PATH,
        )

    def _LoadProductSmokeRecords(self) -> List[Dict[str, Any]]:
        if not DEFAULT_PRODUCT_SMOKE_SUMMARY_ARTIFACT_PATH.exists():
            return []
        try:
            rawData = json.loads(
                DEFAULT_PRODUCT_SMOKE_SUMMARY_ARTIFACT_PATH.read_text(
                    encoding="utf-8",
                )
            )
        except Exception:
            return []
        if isinstance(rawData, list):
            return [
                item
                for item in rawData
                if isinstance(item, dict)
            ]
        if isinstance(rawData, dict):
            return [rawData]
        return []

    def _BuildTextPreview(self, text: str) -> str:
        if len(text) <= DEFAULT_TEXT_PREVIEW_CHARACTERS:
            return text
        return f"{text[:DEFAULT_TEXT_PREVIEW_CHARACTERS]}..."

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
