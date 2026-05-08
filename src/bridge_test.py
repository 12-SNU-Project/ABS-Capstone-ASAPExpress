"""수동 local LLM SearchPlan smoke test.

이 파일은 package 내부가 아니라 `src/` 바로 아래에 둔다.
그래야 `python src/runtime_smoke.py`로 직접 실행해도 `eu_export` import가 안정적이다.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

from eu_export import (
    BuildRuntimeAdapter,
    LocalLlmRuntimeConfig,
    LocalLlmRuntimeKind,
    RuntimeAdapter,
    RuntimeDependencyStatus,
)
from eu_export.product import (
    LlmQueryInterpreter,
    QueryAnalysisResult,
    QueryAnalyzer,
    QueryPlanningPipeline,
    QueryPlanningResult,
    SearchPlan,
    SearchPlanValidator,
)


DEFAULT_OMLX_ENDPOINT_URL = "http://127.0.0.1:8000"
DEFAULT_OLLAMA_ENDPOINT_URL = "http://localhost:11434"
PROJECT_ROOT_PATH = Path(__file__).resolve().parent.parent
DEFAULT_DOTENV_PATH = PROJECT_ROOT_PATH / ".env"
DEFAULT_SEARCH_QUERY = "농심 신라면 120g"


def LoadRuntimeEnvironment() -> None:
    load_dotenv(dotenv_path=DEFAULT_DOTENV_PATH)


def ReadEnvironmentValue(primaryName: str, legacyName: str | None = None) -> str | None:
    primaryValue = os.environ.get(primaryName)
    if primaryValue is not None and primaryValue.strip() != "":
        return primaryValue

    if legacyName is None:
        return None

    legacyValue = os.environ.get(legacyName)
    if legacyValue is not None and legacyValue.strip() != "":
        return legacyValue

    return None


def ReadRuntimeKind() -> LocalLlmRuntimeKind:
    runtimeKind = ReadEnvironmentValue("EU_EXPORT_RUNTIME", "EU_FOOD_RUNTIME")
    if runtimeKind is None:
        runtimeKind = "omlx"
    runtimeKind = runtimeKind.strip().lower()
    if runtimeKind == "ollama":
        return LocalLlmRuntimeKind.OLLAMA
    return LocalLlmRuntimeKind.OMLX


def ReadEndpointUrl(runtimeKind: LocalLlmRuntimeKind) -> str:
    endpointUrl = ReadEnvironmentValue("EU_EXPORT_ENDPOINT", "EU_FOOD_ENDPOINT")
    if endpointUrl is not None and endpointUrl.strip() != "":
        return endpointUrl

    if runtimeKind == LocalLlmRuntimeKind.OLLAMA:
        return DEFAULT_OLLAMA_ENDPOINT_URL
    return DEFAULT_OMLX_ENDPOINT_URL


def ReadModelName() -> str:
    modelName = ReadEnvironmentValue("EU_EXPORT_MODEL", "EU_FOOD_MODEL")
    if modelName is None or modelName.strip() == "":
        raise ValueError("Set EU_EXPORT_MODEL before running runtime_smoke.py.")
    return modelName


def ReadTimeoutSeconds() -> int | None:
    timeoutSeconds = ReadEnvironmentValue(
        "EU_EXPORT_TIMEOUT_SECONDS",
        "EU_FOOD_TIMEOUT_SECONDS",
    )
    if timeoutSeconds is None or timeoutSeconds.strip() == "":
        return None

    try:
        parsedTimeoutSeconds = int(timeoutSeconds)
    except ValueError as error:
        raise ValueError("EU_EXPORT_TIMEOUT_SECONDS must be an integer.") from error

    if parsedTimeoutSeconds <= 0:
        raise ValueError("EU_EXPORT_TIMEOUT_SECONDS must be greater than 0.")

    return parsedTimeoutSeconds


def ReadApiKey() -> str | None:
    apiKey = ReadEnvironmentValue("EU_EXPORT_API_KEY", "EU_FOOD_API_KEY")
    if apiKey is None or apiKey.strip() == "":
        apiKey = os.environ.get("OMLX_API_KEY")

    if apiKey is None or apiKey.strip() == "":
        return None

    return apiKey


def ReadSearchQuery() -> str:
    searchQuery = ReadEnvironmentValue(
        "EU_EXPORT_SEARCH_QUERY",
        "EU_FOOD_SEARCH_QUERY",
    )
    if searchQuery is None or searchQuery.strip() == "":
        return DEFAULT_SEARCH_QUERY

    return searchQuery.strip()


def BuildRuntimeAdapterForSmokeTest() -> RuntimeAdapter[Any]:
    runtimeKind = ReadRuntimeKind()
    endpointUrl = ReadEndpointUrl(runtimeKind)
    modelName = ReadModelName()
    timeoutSeconds = ReadTimeoutSeconds()
    apiKey = ReadApiKey()
    extraOptions: Dict[str, Any] = {}
    if timeoutSeconds is not None:
        extraOptions["timeout_seconds"] = timeoutSeconds
    if apiKey is not None:
        extraOptions["api_key"] = apiKey

    runtimeConfig = LocalLlmRuntimeConfig(
        runtimeKind=runtimeKind,
        modelName=modelName,
        endpointUrl=endpointUrl,
        extraOptions=extraOptions,
    )
    dependencyStatus = RuntimeDependencyStatus(
        runtimeKind=runtimeKind,
        isAvailable=True,
        message="manual smoke test",
        endpointUrl=endpointUrl,
    )

    return BuildRuntimeAdapter(runtimeConfig, dependencyStatus=dependencyStatus)


def BuildAnalysisOutput(analysisResult: QueryAnalysisResult) -> Dict[str, Any]:
    return {
        "original_query": analysisResult.originalQuery,
        "normalized_query": analysisResult.normalizedQuery,
        "query_type": analysisResult.queryType.value,
        "product_domain_hint": analysisResult.productDomainHint.value,
        "confidence": analysisResult.confidence,
        "reason": analysisResult.reason,
        "extracted_terms": analysisResult.extractedTerms,
        "limitations": analysisResult.limitations,
    }


def BuildSearchPlanOutput(searchPlan: SearchPlan) -> Dict[str, Any]:
    return {
        "original_query": searchPlan.originalQuery,
        "normalized_query": searchPlan.normalizedQuery,
        "query_type": searchPlan.queryType.value,
        "product_domain_hint": searchPlan.productDomainHint.value,
        "search_queries": searchPlan.searchQueries,
        "preferred_source_types": searchPlan.preferredSourceTypes,
        "requires_web_search": searchPlan.requiresWebSearch,
        "requires_product_detail_pages": searchPlan.requiresProductDetailPages,
        "confidence": searchPlan.confidence,
        "reason": searchPlan.reason,
        "limitations": searchPlan.limitations,
    }


def BuildPlanningErrorOutput(planningResult: QueryPlanningResult) -> Dict[str, Any]:
    return {
        "raw_query": planningResult.rawQuery,
        "errors": planningResult.errors,
    }


def PrintJson(title: str, data: Dict[str, Any]) -> None:
    print(title)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def RunRuntimeSmokeTest() -> None:
    LoadRuntimeEnvironment()

    rawQuery = ReadSearchQuery()
    adapter = BuildRuntimeAdapterForSmokeTest()
    pipeline = QueryPlanningPipeline(
        QueryAnalyzer(),
        LlmQueryInterpreter(adapter),
        SearchPlanValidator(),
    )
    planningResult = pipeline.Plan(rawQuery)

    PrintJson(
        "Heuristic Analysis",
        BuildAnalysisOutput(planningResult.analysisResult),
    )
    if planningResult.candidateData:
        PrintJson("LLM Candidate SearchPlan JSON", planningResult.candidateData)

    if not planningResult.isSuccess or planningResult.searchPlan is None:
        PrintJson("Query Planning Failed", BuildPlanningErrorOutput(planningResult))
        return

    PrintJson(
        "Validated SearchPlan",
        BuildSearchPlanOutput(planningResult.searchPlan),
    )


if __name__ == "__main__":
    RunRuntimeSmokeTest()
