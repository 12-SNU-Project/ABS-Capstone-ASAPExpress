"""상품명 query에서 SearchPlan을 만들고 필요하면 검색 API를 호출하는 smoke test."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

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
    QueryAnalyzer,
    QueryPlanningPipeline,
    SearchPlanValidator,
)
from eu_export.search import SearchExecutor, SearchResultItem, TavilySearchClient


PROJECT_ROOT_PATH = Path(__file__).resolve().parent.parent
DEFAULT_DOTENV_PATH = PROJECT_ROOT_PATH / ".env"
DEFAULT_SEARCH_QUERY = "농심 신라면 120g"
DEFAULT_RUNTIME_KIND = "omlx"
DEFAULT_OMLX_ENDPOINT_URL = "http://127.0.0.1:8000"
DEFAULT_OLLAMA_ENDPOINT_URL = "http://localhost:11434"
DEFAULT_RUNTIME_TIMEOUT_SECONDS = 120
DEFAULT_SEARCH_RESULT_COUNT = 5
DEFAULT_SEARCH_TIMEOUT_SECONDS = 20


def LoadEnvironment() -> None:
    load_dotenv(dotenv_path=DEFAULT_DOTENV_PATH)


def ReadEnvironmentValue(envName: str) -> str | None:
    envValue = os.environ.get(envName)
    if envValue is None or envValue.strip() == "":
        return None
    return envValue.strip()


def ReadPositiveInteger(envName: str, defaultValue: int) -> int:
    envValue = ReadEnvironmentValue(envName)
    if envValue is None:
        return defaultValue

    try:
        parsedValue = int(envValue)
    except ValueError as error:
        raise ValueError("{0} must be an integer.".format(envName)) from error

    if parsedValue <= 0:
        raise ValueError("{0} must be greater than 0.".format(envName))

    return parsedValue


def ReadRuntimeKind() -> LocalLlmRuntimeKind:
    runtimeKind = ReadEnvironmentValue("EU_EXPORT_RUNTIME") or DEFAULT_RUNTIME_KIND
    if runtimeKind.lower() == "ollama":
        return LocalLlmRuntimeKind.OLLAMA
    return LocalLlmRuntimeKind.OMLX


def ReadEndpointUrl(runtimeKind: LocalLlmRuntimeKind) -> str:
    endpointUrl = ReadEnvironmentValue("EU_EXPORT_ENDPOINT")
    if endpointUrl is not None:
        return endpointUrl

    if runtimeKind == LocalLlmRuntimeKind.OLLAMA:
        return DEFAULT_OLLAMA_ENDPOINT_URL
    return DEFAULT_OMLX_ENDPOINT_URL


def ReadRequiredEnvironmentValue(envName: str) -> str:
    envValue = ReadEnvironmentValue(envName)
    if envValue is None:
        raise ValueError("Set {0} before running search_test.py.".format(envName))
    return envValue


def BuildRuntimeAdapterForSmokeTest() -> RuntimeAdapter[Any]:
    runtimeKind = ReadRuntimeKind()
    endpointUrl = ReadEndpointUrl(runtimeKind)
    extraOptions: Dict[str, Any] = {
        "timeout_seconds": ReadPositiveInteger(
            "EU_EXPORT_TIMEOUT_SECONDS",
            DEFAULT_RUNTIME_TIMEOUT_SECONDS,
        ),
    }
    apiKey = ReadEnvironmentValue("EU_EXPORT_API_KEY")
    if apiKey is not None:
        extraOptions["api_key"] = apiKey

    runtimeConfig = LocalLlmRuntimeConfig(
        runtimeKind=runtimeKind,
        modelName=ReadRequiredEnvironmentValue("EU_EXPORT_MODEL"),
        endpointUrl=endpointUrl,
        extraOptions=extraOptions,
    )
    dependencyStatus = RuntimeDependencyStatus(
        runtimeKind=runtimeKind,
        isAvailable=True,
        message="manual search smoke test",
        endpointUrl=endpointUrl,
    )

    return BuildRuntimeAdapter(runtimeConfig, dependencyStatus=dependencyStatus)


def BuildSearchResultOutput(resultItems: List[SearchResultItem]) -> Dict[str, Any]:
    return {
        "result_count": len(resultItems),
        "items": [
            {
                "rank": resultItem.rank,
                "query": resultItem.query,
                "title": resultItem.title,
                "url": resultItem.url,
                "snippet": resultItem.snippet,
                "source_provider": resultItem.sourceProvider,
            }
            for resultItem in resultItems
        ],
    }


def PrintJson(title: str, data: Dict[str, Any]) -> None:
    print(title)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def RunSearchSmokeTest() -> None:
    LoadEnvironment()

    rawQuery = ReadEnvironmentValue("EU_EXPORT_SEARCH_QUERY") or DEFAULT_SEARCH_QUERY
    planningPipeline = QueryPlanningPipeline(
        QueryAnalyzer(),
        LlmQueryInterpreter(BuildRuntimeAdapterForSmokeTest()),
        SearchPlanValidator(),
    )
    planningResult = planningPipeline.Plan(rawQuery)

    if not planningResult.isSuccess or planningResult.searchPlan is None:
        PrintJson(
            "Query Planning Failed",
            {
                "raw_query": planningResult.rawQuery,
                "query_type": planningResult.analysisResult.queryType.value,
                "product_domain_hint": (
                    planningResult.analysisResult.productDomainHint.value
                ),
                "errors": planningResult.errors,
                "candidate_data": planningResult.candidateData,
            },
        )
        return

    PrintJson(
        "Validated SearchPlan",
        {
            "raw_query": planningResult.rawQuery,
            "query_type": planningResult.searchPlan.queryType.value,
            "product_domain_hint": planningResult.searchPlan.productDomainHint.value,
            "requires_web_search": planningResult.searchPlan.requiresWebSearch,
            "requires_product_detail_pages": (
                planningResult.searchPlan.requiresProductDetailPages
            ),
            "search_queries": planningResult.searchPlan.searchQueries,
        },
    )

    if not planningResult.searchPlan.requiresWebSearch:
        return

    searchClient = TavilySearchClient(
        apiKey=ReadRequiredEnvironmentValue("EU_EXPORT_TAVILY_API_KEY"),
        timeoutSeconds=ReadPositiveInteger(
            "EU_EXPORT_SEARCH_TIMEOUT_SECONDS",
            DEFAULT_SEARCH_TIMEOUT_SECONDS,
        ),
    )
    searchExecutor = SearchExecutor(
        searchClient,
        maxResultsPerQuery=ReadPositiveInteger(
            "EU_EXPORT_SEARCH_RESULT_COUNT",
            DEFAULT_SEARCH_RESULT_COUNT,
        ),
    )
    searchResult = searchExecutor.Execute(planningResult.searchPlan)
    PrintJson("Search API Result", BuildSearchResultOutput(searchResult.resultItems))

    if searchResult.errors:
        PrintJson("Search API Errors", {"errors": searchResult.errors})


if __name__ == "__main__":
    RunSearchSmokeTest()
