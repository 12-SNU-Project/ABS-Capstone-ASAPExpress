"""SearchPlan -> Playwright/PaddleOCR -> product fact smoke flow."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT_PATH = Path(__file__).resolve().parent
SOURCE_ROOT_PATH = PROJECT_ROOT_PATH / "src"
if str(SOURCE_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT_PATH))

from eu_export import (
    BuildDefaultProductSourcePolicy,
    BuildRuntimeAdapter,
    DEFAULT_BEAUTY_KURLY_SCROLL_URL,
    LlmRuntimeConfig,
    LlmRuntimeKind,
    LlmQueryInterpreter,
    PaddleOcrEngine,
    ProductFactExtractor,
    ProductSourceCollectionPipeline,
    ProductSourceFetcher,
    ProductSourceRanker,
    QueryAnalyzer,
    QueryPlanningPipeline,
    RuntimeAdapter,
    RuntimeDependencyStatus,
    SearchPlan,
    SearchPlanValidator,
    SearchResultItem,
)


DEFAULT_DOTENV_PATH = PROJECT_ROOT_PATH / ".env"
DEFAULT_RUNTIME_KIND = "omlx"
DEFAULT_OMLX_ENDPOINT_URL = "http://127.0.0.1:8000"
DEFAULT_OLLAMA_ENDPOINT_URL = "http://localhost:11434"
DEFAULT_OPENAI_ENDPOINT_URL = "https://api.openai.com"
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_SMOKE_QUERY = "라로슈포제 시카플라스트 라방 B5 클렌저 200ml 뷰티컬리"
DEFAULT_SMOKE_PRODUCT_URL = "https://www.kurly.com/goods/5071600"
DEFAULT_SMOKE_PRODUCT_TITLE = (
    "[라로슈포제] 시카플라스트 라방 B5 클렌저 200ml (약산성 젤 클렌저)"
)
DEFAULT_SMOKE_PRODUCT_SNIPPET = "민감 피부를 위한 순한 젤 클렌저"
DEFAULT_ARTIFACT_FILE_PREFIX = "product-source"


def LoadEnvironment() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv(dotenv_path=DEFAULT_DOTENV_PATH)


def ReadEnvironmentValue(envName: str) -> Optional[str]:
    envValue = os.environ.get(envName)
    if envValue is None or envValue.strip() == "":
        return None
    return envValue.strip()


def ReadBooleanEnvironmentValue(envName: str, defaultValue: bool) -> bool:
    envValue = ReadEnvironmentValue(envName)
    if envValue is None:
        return defaultValue

    return envValue.lower() in {"1", "true", "yes", "y", "on"}


def ReadPositiveIntegerEnvironmentValue(envName: str, defaultValue: int) -> int:
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


def BuildArgumentParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a live smoke flow from local LLM SearchPlan generation "
            "to Beauty Kurly page fetch and product fact extraction."
        )
    )
    parser.add_argument(
        "--query",
        default=ReadEnvironmentValue("EU_EXPORT_SMOKE_QUERY") or DEFAULT_SMOKE_QUERY,
    )
    parser.add_argument(
        "--product-url",
        default=ReadEnvironmentValue("EU_EXPORT_SMOKE_PRODUCT_URL")
        or DEFAULT_SMOKE_PRODUCT_URL,
        help=(
            "Configured product URL seed. "
            "This is a real URL seed, not a fake API response."
        ),
    )
    parser.add_argument(
        "--product-title",
        default=ReadEnvironmentValue("EU_EXPORT_SMOKE_PRODUCT_TITLE")
        or DEFAULT_SMOKE_PRODUCT_TITLE,
    )
    parser.add_argument(
        "--product-snippet",
        default=ReadEnvironmentValue("EU_EXPORT_SMOKE_PRODUCT_SNIPPET")
        or DEFAULT_SMOKE_PRODUCT_SNIPPET,
    )
    parser.add_argument(
        "--beauty-kurly-url",
        default=ReadEnvironmentValue("EU_EXPORT_BEAUTY_KURLY_URL")
        or DEFAULT_BEAUTY_KURLY_SCROLL_URL,
    )
    parser.add_argument(
        "--runtime",
        default=ReadEnvironmentValue("EU_EXPORT_RUNTIME") or DEFAULT_RUNTIME_KIND,
        choices=["omlx", "ollama", "openai"],
    )
    parser.add_argument(
        "--model",
        default=ReadEnvironmentValue("EU_EXPORT_MODEL"),
    )
    parser.add_argument(
        "--endpoint",
        default=ReadEnvironmentValue("EU_EXPORT_ENDPOINT"),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=ReadPositiveIntegerEnvironmentValue(
            "EU_EXPORT_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
        ),
    )
    parser.add_argument(
        "--scroll-count",
        type=int,
        default=ReadPositiveIntegerEnvironmentValue(
            "EU_EXPORT_SMOKE_SCROLL_COUNT",
            6,
        ),
    )
    parser.add_argument(
        "--max-product-pages",
        type=int,
        default=ReadPositiveIntegerEnvironmentValue(
            "EU_EXPORT_SMOKE_MAX_PRODUCT_PAGES",
            1,
        ),
    )
    parser.add_argument(
        "--ocr-lang",
        default=ReadEnvironmentValue("EU_EXPORT_PADDLE_OCR_LANG") or "korean",
    )
    parser.add_argument(
        "--ocr-device",
        default=ReadEnvironmentValue("EU_EXPORT_PADDLE_OCR_DEVICE"),
    )
    parser.add_argument(
        "--ocr-image-dir",
        default=ReadEnvironmentValue("EU_EXPORT_SMOKE_OCR_IMAGE_DIR"),
        help=(
            "Optional directory for Playwright screenshots used as OCR input. "
            "When omitted, no screenshot file is written."
        ),
    )
    parser.add_argument(
        "--require-ocr-text",
        action="store_true",
        default=ReadBooleanEnvironmentValue(
            "EU_EXPORT_SMOKE_REQUIRE_OCR_TEXT",
            False,
        ),
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        default=not ReadBooleanEnvironmentValue("EU_EXPORT_SMOKE_USE_OCR", True),
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        default=not ReadBooleanEnvironmentValue("EU_EXPORT_SMOKE_HEADLESS", True),
    )
    parser.add_argument(
        "--supports-response-format",
        action="store_true",
        default=ReadBooleanEnvironmentValue(
            "EU_EXPORT_SUPPORTS_RESPONSE_FORMAT",
            False,
        ),
    )
    return parser


def BuildRuntimeAdapterForSmoke(args: argparse.Namespace) -> RuntimeAdapter[Any]:
    if args.model is None or args.model.strip() == "":
        raise ValueError("Set EU_EXPORT_MODEL or pass --model.")

    runtimeKind = LlmRuntimeKind(args.runtime)
    endpointUrl = args.endpoint or ReadDefaultEndpointUrl(runtimeKind)
    extraOptions: Dict[str, Any] = {
        "timeout_seconds": args.timeout_seconds,
    }
    apiKey = ReadEnvironmentValue("EU_EXPORT_API_KEY")
    if apiKey is not None:
        extraOptions["api_key"] = apiKey
    if args.supports_response_format:
        extraOptions["supports_response_format"] = True

    runtimeConfig = LlmRuntimeConfig(
        runtimeKind=runtimeKind,
        modelName=args.model.strip(),
        endpointUrl=endpointUrl,
        extraOptions=extraOptions,
    )
    dependencyStatus = RuntimeDependencyStatus(
        runtimeKind=runtimeKind,
        isAvailable=True,
        message="manual product source smoke test",
        endpointUrl=endpointUrl,
    )

    return BuildRuntimeAdapter(
        runtimeConfig,
        dependencyStatus=dependencyStatus,
    )


def ReadDefaultEndpointUrl(runtimeKind: LlmRuntimeKind) -> str:
    if runtimeKind == LlmRuntimeKind.OLLAMA:
        return DEFAULT_OLLAMA_ENDPOINT_URL
    if runtimeKind == LlmRuntimeKind.OPENAI:
        return DEFAULT_OPENAI_ENDPOINT_URL
    return DEFAULT_OMLX_ENDPOINT_URL


def BuildSearchPlan(args: argparse.Namespace) -> SearchPlan:
    adapter = BuildRuntimeAdapterForSmoke(args)
    queryPlanningPipeline = QueryPlanningPipeline(
        queryAnalyzer=QueryAnalyzer(),
        queryInterpreter=LlmQueryInterpreter(adapter),
        searchPlanValidator=SearchPlanValidator(),
    )
    planningResult = queryPlanningPipeline.Plan(args.query)
    if not planningResult.isSuccess or planningResult.searchPlan is None:
        PrintJson(
            "SearchPlan generation failed",
            {
                "raw_query": planningResult.rawQuery,
                "candidate_data": planningResult.candidateData,
                "errors": planningResult.errors,
            },
        )
        raise SystemExit(1)

    return planningResult.searchPlan


def BuildConfiguredSearchResults(
    args: argparse.Namespace,
    searchPlan: SearchPlan,
) -> List[SearchResultItem]:
    if args.product_url is None or args.product_url.strip() == "":
        return []

    return [
        SearchResultItem(
            title=args.product_title,
            url=args.product_url,
            snippet=args.product_snippet,
            sourceProvider="configured_seed",
            query=searchPlan.normalizedQuery,
            rank=1,
            rawData={
                "seed_type": "manual_real_url",
            },
        )
    ]


def BuildCollectionPipeline(
    args: argparse.Namespace,
) -> ProductSourceCollectionPipeline:
    sourcePolicy = BuildDefaultProductSourcePolicy()
    ocrEngine = None
    if not args.no_ocr:
        ocrEngine = PaddleOcrEngine(
            lang=args.ocr_lang,
            device=args.ocr_device,
        )

    return ProductSourceCollectionPipeline(
        sourceRanker=ProductSourceRanker(
            sourcePolicy,
            defaultBeautyKurlyScrollUrl=args.beauty_kurly_url,
        ),
        sourceFetcher=ProductSourceFetcher(
            sourcePolicy=sourcePolicy,
            ocrEngine=ocrEngine,
            headless=not args.headed,
            timeoutMilliseconds=args.timeout_seconds * 1000,
            scrollCount=args.scroll_count,
        ),
        factExtractor=ProductFactExtractor(),
        maxProductPagesToFetch=args.max_product_pages,
    )


def SearchPlanToDict(searchPlan: SearchPlan) -> Dict[str, Any]:
    return {
        "original_query": searchPlan.originalQuery,
        "normalized_query": searchPlan.normalizedQuery,
        "query_type": searchPlan.queryType.value,
        "product_domain_hint": searchPlan.productDomainHint.value,
        "search_product_domains": [
            productDomain.value for productDomain in searchPlan.searchProductDomains
        ],
        "search_queries": list(searchPlan.searchQueries),
        "preferred_source_types": list(searchPlan.preferredSourceTypes),
        "requires_web_search": searchPlan.requiresWebSearch,
        "requires_product_detail_pages": searchPlan.requiresProductDetailPages,
        "confidence": searchPlan.confidence,
        "reason": searchPlan.reason,
        "limitations": list(searchPlan.limitations),
    }


def PrintJson(title: str, data: Dict[str, Any]) -> None:
    print(title)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def WriteOcrImageArtifacts(
    args: argparse.Namespace,
    collectionResult: Any,
) -> List[str]:
    if args.ocr_image_dir is None or args.ocr_image_dir.strip() == "":
        return []

    artifactDirectory = Path(args.ocr_image_dir).expanduser()
    if not artifactDirectory.is_absolute():
        artifactDirectory = PROJECT_ROOT_PATH / artifactDirectory
    artifactDirectory.mkdir(parents=True, exist_ok=True)

    artifactPaths: List[str] = []
    for index, fetchedSource in enumerate(collectionResult.fetchedSources, start=1):
        if fetchedSource.screenshotBytes is None:
            continue

        artifactPath = artifactDirectory / "{0}-{1:02d}.png".format(
            DEFAULT_ARTIFACT_FILE_PREFIX,
            index,
        )
        artifactPath.write_bytes(fetchedSource.screenshotBytes)
        artifactPaths.append(str(artifactPath))

    return artifactPaths


def ValidateSmokeResult(
    args: argparse.Namespace,
    collectionResult: Any,
    ocrImagePaths: List[str],
) -> List[str]:
    errors: List[str] = []
    if not collectionResult.factPackages:
        errors.append("no product fact package was extracted")

    if not collectionResult.fetchedSources:
        errors.append("no product source page was fetched")

    for index, factPackage in enumerate(collectionResult.factPackages, start=1):
        productInformation = factPackage.productInformation
        if productInformation.productName == "unknown product":
            errors.append("fact package {0} has unknown product name".format(index))
        if productInformation.productPageUrl.strip() == "":
            errors.append("fact package {0} has empty product page URL".format(index))
        if not factPackage.sourceTexts:
            errors.append("fact package {0} has no source text excerpt".format(index))

    if args.ocr_image_dir is not None and not ocrImagePaths:
        errors.append("ocr image output directory was set but no screenshot was written")

    if args.require_ocr_text:
        hasOcrText = any(
            fetchedSource.ocrText is not None
            and fetchedSource.ocrText.strip() != ""
            for fetchedSource in collectionResult.fetchedSources
        )
        if not hasOcrText:
            errors.append("OCR text was required but no OCR text was extracted")

    return errors


def RunProductSourceSmoke() -> None:
    LoadEnvironment()
    args = BuildArgumentParser().parse_args()

    searchPlan = BuildSearchPlan(args)
    collectionPipeline = BuildCollectionPipeline(args)
    collectionResult = collectionPipeline.Collect(
        searchPlan,
        BuildConfiguredSearchResults(args, searchPlan),
    )
    ocrImagePaths = WriteOcrImageArtifacts(args, collectionResult)
    validationErrors = ValidateSmokeResult(
        args,
        collectionResult,
        ocrImagePaths,
    )

    PrintJson(
        "Product Source Smoke Result",
        {
            "search_plan": SearchPlanToDict(searchPlan),
            "ranked_candidates": [
                candidate.ToDict()
                for candidate in collectionResult.rankedCandidates[:5]
            ],
            "fetched_sources": [
                fetchedSource.ToDict()
                for fetchedSource in collectionResult.fetchedSources
            ],
            "fact_packages": [
                factPackage.ToDict()
                for factPackage in collectionResult.factPackages
            ],
            "ocr_image_paths": ocrImagePaths,
            "errors": collectionResult.errors,
            "validation_errors": validationErrors,
        },
    )

    if validationErrors:
        raise SystemExit(2)


if __name__ == "__main__":
    RunProductSourceSmoke()
