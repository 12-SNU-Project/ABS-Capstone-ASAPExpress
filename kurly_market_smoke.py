"""KurlyMarket 상품 페이지 parser/OCR fallback runtime smoke."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List

from loguru import logger


PROJECT_ROOT_PATH = Path(__file__).resolve().parent
SOURCE_ROOT_PATH = PROJECT_ROOT_PATH / "src"
if str(SOURCE_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT_PATH))

from bussiness_logic.product import (  # noqa: E402
    KurlyGlobalPageParser,
    KurlyPageAdapter,
    KurlyPageCollector,
    KurlyDomesticPageParser,
    KurlyProductPipeline,
    KurlyPipelineInput,
    PaddleOcrEngine,
    PaddleOcrVlEngine,
)
from bussiness_logic.app_config import LoadAppConfig  # noqa: E402
from bussiness_logic.artifact_paths import ExtractProductIdFromUrl  # noqa: E402
from bussiness_logic.bridge import (  # noqa: E402
    BuildLlmRuntimeConfigFromEnv,
    BuildRuntimeAdapter,
    RuntimeAdapterBuildError,
)
from bussiness_logic.input_process import ProductInputReconstructionService  # noqa: E402
from bussiness_logic.product.ocr.ocr_fallback import (  # noqa: E402
    ProductOcrImageDownloader,
    ProductOcrImageResult,
)


def ParseArguments(arguments: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kurly web scroll/OCR/LLM reconstruction smoke CLI",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="브라우저를 열어 appconfig URL의 스크롤 과정을 표시합니다.",
    )
    parser.add_argument(
        "--compare-ocr",
        action="store_true",
        help="동일 이미지의 raw OCR, PP-StructureV3, PaddleOCR-VL 결과를 비교합니다.",
    )
    parser.add_argument(
        "--compare-max-images",
        type=int,
        default=1,
        metavar="N",
        help="상품별 비교 이미지 수입니다. 기본 1, 0이면 전체입니다.",
    )
    parsedArguments = parser.parse_args(arguments)
    if parsedArguments.compare_max_images < 0:
        parser.error("--compare-max-images must be greater than or equal to 0")
    return parsedArguments


class KurlyMarketSmokeRunner:
    """실제 KurlyMarket URL에서 parser와 선택적 OCR fallback을 확인한다."""

    def __init__(
        self,
        *,
        showBrowser: bool = False,
        compareOcr: bool = False,
        compareMaxImages: int = 1,
    ) -> None:
        appConfig = LoadAppConfig(PROJECT_ROOT_PATH)
        pathConfig = appConfig.paths
        smokeConfig = appConfig.kurly_smoke

        self._productUrls = list(smokeConfig.product_urls)
        self._timeoutSeconds = smokeConfig.timeout_seconds
        self._scrollCount = smokeConfig.scroll_count
        self._headless = False if showBrowser else smokeConfig.headless
        self._compareOcr = compareOcr
        self._compareMaxImages = compareMaxImages
        self._runOcrFallback = smokeConfig.run_ocr_fallback
        self._useStructuredOcr = smokeConfig.use_structured_ocr
        self._maxOcrImageCount = smokeConfig.max_ocr_image_count
        self._structuredOcrMaxTileHeightPixels = (
            smokeConfig.structured_ocr_max_tile_height_pixels
        )
        self._structuredOcrMaxTileSidePixels = (
            smokeConfig.structured_ocr_max_tile_side_pixels
        )
        self._structuredOcrTileOverlapPixels = (
            smokeConfig.structured_ocr_tile_overlap_pixels
        )
        self._structuredOcrUseProjectionTiling = (
            smokeConfig.structured_ocr_use_projection_tiling
        )
        self._structuredOcrAllowHardCutFallback = (
            smokeConfig.structured_ocr_allow_hard_cut_fallback
        )
        self._structuredOcrVlExtraOptions = (
            smokeConfig.BuildStructuredOcrVlExtraOptions()
        )
        self._useInputReconstruction = smokeConfig.use_input_reconstruction
        self._useLlmInputReconstruction = smokeConfig.use_llm_input_reconstruction
        self._writeLlmInputReconstructionDebugArtifacts = (
            smokeConfig.write_llm_input_reconstruction_debug_artifacts
        )
        self._llmInputReconstructionMaxTokens = (
            smokeConfig.llm_input_reconstruction_max_tokens
        )
        self._inputDictionaryPath = (
            pathConfig.ResolvePath(PROJECT_ROOT_PATH, smokeConfig.input_dictionary_path)
            if smokeConfig.input_dictionary_path is not None
            else None
        )
        self._inputDictionaryFuzzyMinRatio = (
            smokeConfig.input_dictionary_fuzzy_min_ratio
        )
        self._writeSummaryArtifact = smokeConfig.write_summary_artifact
        self._logFullResult = smokeConfig.log_full_result
        self._artifactRootPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            pathConfig.kurly_smoke_artifact_root,
        )
        self._summaryArtifactPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            pathConfig.kurly_smoke_summary_artifact,
        )
        self._maxLoggedNoticeOptions = smokeConfig.max_logged_notice_options
        self._maxLoggedFieldsPerOption = smokeConfig.max_logged_fields_per_option
        self._maxLoggedOcrCandidateUrls = smokeConfig.max_logged_ocr_candidate_urls
        self._fieldValuePreviewCharacters = smokeConfig.field_value_preview_characters
        self._ocrTextPreviewCharacters = smokeConfig.ocr_text_preview_characters
        self._pipelineOcrEngine: Any = None
        self._pipelineRawOcrEngine: Any = None

    def Run(self) -> None:
        self._ConfigureLogger()
        runLogger = self._Logger("Run")
        runLogger.info(
            (
                "KurlyMarket 상품 수집 smoke를 시작합니다 url_count={} "
                "run_ocr_fallback={} browser_mode={} compare_ocr={}"
            ),
            len(self._productUrls),
            self._runOcrFallback,
            "headless" if self._headless else "headed",
            self._compareOcr,
        )
        if not self._productUrls:
            runLogger.warning(
                (
                    "실행할 상품 URL이 없습니다. .appconfig의 "
                    "[kurly_smoke].product_urls에 국내/해외 Kurly 상품 링크를 "
                    "넣어주세요."
                )
            )
            if self._writeSummaryArtifact:
                self._WriteSummaryArtifact([])
            return

        runLogger.info("STEP 1/4 상품 페이지 수집/OCR 파이프라인을 준비합니다")
        productSourcePipeline = self._BuildProductSourcePipeline()

        runLogger.info(
            "STEP 2/4 KurlyMarket 상품 페이지를 수집합니다 url_count={}",
            len(self._productUrls),
        )
        results: List[Dict[str, Any]] = []
        for productIndex, productUrl in enumerate(self._productUrls, start=1):
            runLogger.info(
                "STEP 2/4 상품 페이지 수집 index={}/{} url={}",
                productIndex,
                len(self._productUrls),
                productUrl,
            )
            resultData = self._RunOne(productSourcePipeline, productUrl)
            results.append(resultData)
            self._LogOne(resultData)

        runLogger.info("STEP 3/4 상품 수집 결과를 요약합니다")
        self._LogSummary(results)
        if self._writeSummaryArtifact:
            runLogger.info("STEP 4/4 상품 수집 결과 JSON artifact를 저장합니다")
            self._WriteSummaryArtifact(results)
        else:
            runLogger.info("STEP 4/4 상품 수집 결과 JSON artifact 저장을 건너뜁니다")

    def _BuildProductSourcePipeline(self) -> KurlyProductPipeline:
        pageAdapter = KurlyPageAdapter(
            domesticParser=KurlyDomesticPageParser(),
            globalParser=KurlyGlobalPageParser(),
        )
        collector = KurlyPageCollector(
            parser=pageAdapter,
            headless=self._headless,
            timeoutMilliseconds=self._timeoutSeconds * 1000,
            scrollCount=self._scrollCount,
        )
        inputReconstructionService = self._BuildInputReconstructionService()
        ocrEngine = None
        screeningOcrEngine = None
        if self._runOcrFallback:
            if self._useStructuredOcr:
                screeningOcrEngine = PaddleOcrEngine()
            ocrEngine = (
                PaddleOcrVlEngine(
                    vlExtraOptions=self._structuredOcrVlExtraOptions,
                    useProjectionTiling=self._structuredOcrUseProjectionTiling,
                    maxTileHeightPixels=self._structuredOcrMaxTileHeightPixels,
                    maxTileSidePixels=self._structuredOcrMaxTileSidePixels,
                    tileOverlapPixels=self._structuredOcrTileOverlapPixels,
                    allowHardCutFallback=self._structuredOcrAllowHardCutFallback,
                )
                if self._useStructuredOcr
                else PaddleOcrEngine()
            )
        self._pipelineOcrEngine = ocrEngine
        self._pipelineRawOcrEngine = screeningOcrEngine
        return KurlyProductPipeline(
            collector=collector,
            ocrEngine=ocrEngine,
            screeningOcrEngine=screeningOcrEngine,
            inputReconstructionService=inputReconstructionService,
        )

    def _BuildInputReconstructionService(self) -> ProductInputReconstructionService | None:
        if not self._useInputReconstruction:
            return None

        runtimeAdapter = None
        if self._useLlmInputReconstruction:
            try:
                runtimeAdapter = BuildRuntimeAdapter(
                    BuildLlmRuntimeConfigFromEnv(projectRootPath=PROJECT_ROOT_PATH),
                    requireAvailable=True,
                )
            except RuntimeAdapterBuildError as error:
                self._Logger("_BuildInputReconstructionService").warning(
                    "LLM input reconstruction disabled because runtime is unavailable: {}",
                    error,
                )

        return ProductInputReconstructionService(
            dictionaryPath=(
                str(self._inputDictionaryPath)
                if self._inputDictionaryPath is not None
                else None
            ),
            runtimeAdapter=runtimeAdapter,
            fuzzyMinRatio=self._inputDictionaryFuzzyMinRatio,
            llmMaxTokens=self._llmInputReconstructionMaxTokens,
            llmDebugArtifactRootPath=(
                self._artifactRootPath
                if (
                    runtimeAdapter is not None
                    and self._writeLlmInputReconstructionDebugArtifacts
                )
                else None
            ),
        )

    def _RunOne(
        self,
        productSourcePipeline: KurlyProductPipeline,
        productUrl: str,
    ) -> Dict[str, Any]:
        try:
            pipelineResult = productSourcePipeline.Run(
                KurlyPipelineInput(
                    productPageUrl=productUrl,
                    runOcrFallback=self._runOcrFallback,
                    artifactRootPath=self._artifactRootPath,
                    maxOcrImageCount=self._maxOcrImageCount,
                )
            )
            resultData = self._BuildResult(
                productUrl,
                pipelineResult.model_dump(mode="json", by_alias=True),
            )
            if self._compareOcr:
                resultData["ocr_comparison"] = self._RunOcrComparison(
                    productUrl,
                    list(pipelineResult.collectionResult.ocrCandidateImageUrls),
                    pipelineResult.ocrImageResults,
                )
            return resultData
        except Exception as error:
            return {
                "product_page_url": productUrl,
                "status": {
                    "is_parse_ok": False,
                    "is_ocr_fallback_ok": False,
                    "runtime_error": str(error),
                },
            }

    def _BuildResult(
        self,
        productUrl: str,
        pipelineResultData: Dict[str, Any],
    ) -> Dict[str, Any]:
        collectionResult = pipelineResultData.get("collection_result")
        if not isinstance(collectionResult, dict):
            collectionResult = pipelineResultData.get("collection_summary", {})
        parsedProductPage = pipelineResultData.get("parsed_product_page")
        if not isinstance(parsedProductPage, dict):
            parsedProductPage = collectionResult["parsed_product_page"]
        ocrSummary = pipelineResultData.get("ocr_summary", {})
        if not isinstance(ocrSummary, dict):
            ocrSummary = {}
        inputReconstruction = pipelineResultData.get("input_reconstruction", {})
        if not isinstance(inputReconstruction, dict):
            inputReconstruction = ocrSummary.get("input_reconstruction", {})
        if not isinstance(inputReconstruction, dict):
            inputReconstruction = {}
        combinedOcrText = pipelineResultData["combined_ocr_text"]
        requiresOcrFallback = parsedProductPage["requires_ocr_fallback"]
        productNoticeFieldCount = parsedProductPage.get(
            "product_notice_field_count",
        )
        if not isinstance(productNoticeFieldCount, int):
            productNoticeFieldCount = self._CountNoticeOptionFields(
                parsedProductPage.get("product_notice_options", []),
            )

        successfulOcrImageCount = int(
            ocrSummary.get("successful_image_count", 0),
        )
        isOcrFallbackOk = (
            not requiresOcrFallback
            or (
                self._runOcrFallback
                and successfulOcrImageCount > 0
            )
        )

        noticeData = {
            "line_count": collectionResult["product_notice_text_line_count"],
            "option_count": len(parsedProductPage["product_notice_options"]),
            "field_count": productNoticeFieldCount,
            "option_names": parsedProductPage["product_notice_option_names"],
            "options_preview": self._BuildOptionPreview(
                parsedProductPage["product_notice_options"],
            ),
            "requires_ocr_fallback": requiresOcrFallback,
            "image_reference_detected": parsedProductPage[
                "image_reference_detected"
            ],
        }
        ocrEvidenceData = {
            "product_detail_image_url_count": collectionResult.get(
                "product_detail_image_url_count",
                len(collectionResult.get("product_detail_image_urls", [])),
            ),
            "candidate_image_url_count": collectionResult.get(
                "ocr_candidate_image_url_count",
                len(collectionResult.get("ocr_candidate_image_urls", [])),
            ),
            "candidate_image_urls_preview": collectionResult.get(
                "ocr_candidate_image_urls",
                [],
            )[:self._maxLoggedOcrCandidateUrls],
            "image_result_count": ocrSummary.get(
                "image_result_count",
                0,
            ),
            "successful_image_count": ocrSummary.get(
                "successful_image_count",
                0,
            ),
            "structured_table_image_count": ocrSummary.get(
                "structured_table_image_count",
                0,
            ),
            "structured_table_count": ocrSummary.get(
                "structured_table_count",
                0,
            ),
            "raw_tile_text_count": ocrSummary.get(
                "raw_tile_text_count",
                0,
            ),
            "raw_text_length": ocrSummary.get(
                "raw_text_length",
                0,
            ),
            "image_artifacts": ocrSummary.get("image_artifacts", []),
            "combined_text_length": len(combinedOcrText),
            "combined_ocr_text": combinedOcrText,
        }
        return {
            "product_page_url": productUrl,
            "status": {
                "is_parse_ok": self._IsParseOk(
                    collectionResult,
                    parsedProductPage,
                    productNoticeFieldCount,
                ),
                "is_ocr_fallback_ok": isOcrFallbackOk,
            },
            "product": {
                "product_name": parsedProductPage["product_name"],
                "product_domain": parsedProductPage["product_domain"],
                "short_description": parsedProductPage["short_description"],
                "brand_name": parsedProductPage["brand_name"],
                "package_type": parsedProductPage["package_type"],
                "sale_unit": parsedProductPage["sale_unit"],
            },
            "raw_collection": {
                "page_collection": collectionResult,
                "rendered_page_evidence": pipelineResultData.get(
                    "rendered_page_evidence_summary",
                ),
                "parsed_product_page": parsedProductPage,
                "notice": noticeData,
                "ocr_evidence": ocrEvidenceData,
            },
            "llm_reconstruction": self._BuildInputReconstructionView(
                inputReconstruction,
            ),
            "pipeline_steps": pipelineResultData["steps"],
            "warnings": collectionResult["warnings"],
            "errors": pipelineResultData["errors"],
        }

    def _RunOcrComparison(
        self,
        productUrl: str,
        imageUrls: List[str],
        pipelineOcrImageResults: List[ProductOcrImageResult],
    ) -> Dict[str, Any]:
        selectedImageUrls = (
            imageUrls
            if self._compareMaxImages == 0
            else imageUrls[:self._compareMaxImages]
        )
        reusablePipelineResults = {
            result.imageUrl: result
            for result in pipelineOcrImageResults
            if result.error is None
        }
        engines: Dict[str, Any] = {}
        if selectedImageUrls:
            from paddleocr import PPStructureV3

            engines = {
                "only_raw_ocr": (
                    self._pipelineRawOcrEngine
                    if isinstance(self._pipelineRawOcrEngine, PaddleOcrEngine)
                    else self._pipelineOcrEngine
                    if isinstance(self._pipelineOcrEngine, PaddleOcrEngine)
                    else PaddleOcrEngine()
                ),
                "only_pp_structure": PPStructureV3(
                    lang="korean",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    use_seal_recognition=False,
                    use_table_recognition=True,
                    use_formula_recognition=False,
                    use_chart_recognition=False,
                    use_region_detection=False,
                    format_block_content=False,
                ),
                "only_vlm": (
                    self._pipelineOcrEngine
                    if isinstance(self._pipelineOcrEngine, PaddleOcrVlEngine)
                    else PaddleOcrVlEngine(
                        vlExtraOptions=self._structuredOcrVlExtraOptions,
                        useProjectionTiling=(
                            self._structuredOcrUseProjectionTiling
                        ),
                        maxTileHeightPixels=(
                            self._structuredOcrMaxTileHeightPixels
                        ),
                        maxTileSidePixels=(
                            self._structuredOcrMaxTileSidePixels
                        ),
                        tileOverlapPixels=self._structuredOcrTileOverlapPixels,
                        allowHardCutFallback=(
                            self._structuredOcrAllowHardCutFallback
                        ),
                    )
                ),
            }
        downloader = ProductOcrImageDownloader()
        imageResults: List[Dict[str, Any]] = []
        for imageIndex, imageUrl in enumerate(selectedImageUrls, start=1):
            try:
                imageBytes = downloader.Download(
                    imageUrl,
                    self._timeoutSeconds,
                )
            except Exception as error:
                imageResults.append(
                    {
                        "index": imageIndex,
                        "image_url": imageUrl,
                        "download_error": str(error),
                        "engines": {},
                    }
                )
                continue
            engineResults = {
                engineName: self._CompareOcrEngine(
                    engineName,
                    engines[engineName],
                    imageBytes,
                )
                for engineName in (
                    "only_raw_ocr",
                    "only_pp_structure",
                    "only_vlm",
                )
            }
            engineResults["production_hybrid"] = (
                self._BuildProductionHybridComparison(
                    reusablePipelineResults[imageUrl]
                )
                if imageUrl in reusablePipelineResults
                else self._BuildSkippedOcrComparison(
                    "pipeline_result_unavailable",
                )
            )
            imageResults.append(
                {
                    "index": imageIndex,
                    "image_url": imageUrl,
                    "image_byte_count": len(imageBytes),
                    "engines": engineResults,
                }
            )

        artifactPath = (
            self._artifactRootPath
            / ExtractProductIdFromUrl(productUrl)
            / "ocr-comparison.json"
        )
        engineTotals: Dict[str, Dict[str, Any]] = {}
        for imageResult in imageResults:
            for engineName, engineResult in (
                imageResult.get("engines", {}) or {}
            ).items():
                total = engineTotals.setdefault(
                    engineName,
                    {
                        "ok_count": 0,
                        "error_count": 0,
                        "skipped_count": 0,
                        "elapsed_seconds": 0.0,
                    },
                )
                status = engineResult.get("status")
                if status == "ok":
                    total["ok_count"] += 1
                    total["elapsed_seconds"] = round(
                        total["elapsed_seconds"]
                        + float(engineResult.get("elapsed_seconds") or 0.0),
                        3,
                    )
                elif status == "skipped":
                    total["skipped_count"] += 1
                else:
                    total["error_count"] += 1
        comparisonData = {
            "product_page_url": productUrl,
            "generated_at": datetime.now().astimezone().isoformat(),
            "comparison_modes": [
                "only_raw_ocr",
                "only_pp_structure",
                "only_vlm",
                "production_hybrid",
            ],
            "vl_backend": self._structuredOcrVlExtraOptions.get("vl_rec_backend"),
            "candidate_image_count": len(imageUrls),
            "image_count": len(imageResults),
            "engine_totals": engineTotals,
            "artifact_path": str(artifactPath),
            "images": imageResults,
        }
        artifactPath.parent.mkdir(parents=True, exist_ok=True)
        artifactPath.write_text(
            json.dumps(comparisonData, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        comparisonLogger = self._Logger("_RunOcrComparison")
        comparisonLogger.info(
            "ocr_comparison_artifact={} engine_totals={}",
            artifactPath,
            engineTotals,
        )
        return {
            "image_count": len(imageResults),
            "engine_totals": engineTotals,
            "artifact_path": str(artifactPath),
        }

    def _BuildProductionHybridComparison(
        self,
        imageResult: ProductOcrImageResult,
    ) -> Dict[str, Any]:
        structuredResult = imageResult.structuredOcr
        text = structuredResult.text
        tableTexts = [table.plainText for table in structuredResult.tables]
        stageTimes = {
            key: value
            for key, value in imageResult.processingTimes.items()
            if key != "download"
        }
        return {
            "status": "ok",
            "elapsed_seconds": round(sum(stageTimes.values()), 3),
            "pipeline_stage_times": stageTimes,
            "text_length": len(text),
            "line_count": len(
                [line for line in text.splitlines() if line.strip()]
            ),
            "table_count": len(tableTexts),
            "text_preview": self._BuildTextPreview(
                text,
                self._ocrTextPreviewCharacters,
            ),
            "text": text,
            "table_texts": tableTexts,
            "warnings": list(structuredResult.warnings),
            "fallback_reason": structuredResult.fallbackReason,
            "table_sources": [
                table.sourceName
                for table in structuredResult.tables
            ],
            "reused_pipeline_result": True,
            "error": None,
        }

    @staticmethod
    def _BuildSkippedOcrComparison(reason: str) -> Dict[str, Any]:
        return {
            "status": "skipped",
            "elapsed_seconds": 0.0,
            "text_length": 0,
            "line_count": 0,
            "table_count": 0,
            "text_preview": "",
            "text": "",
            "table_texts": [],
            "warnings": [],
            "error": reason,
        }

    def _CompareOcrEngine(
        self,
        engineName: str,
        engine: Any,
        imageBytes: bytes,
    ) -> Dict[str, Any]:
        startedAt = perf_counter()
        text = ""
        tableTexts: List[str] = []
        warnings: List[str] = []
        extra: Dict[str, Any] = {}
        try:
            if engineName == "only_raw_ocr":
                text = engine.ExtractTextFromImage(imageBytes)
            elif engineName == "only_vlm":
                result = engine.ExtractStructuredTextFromImage(imageBytes)
                text = result.text
                tableTexts = [table.plainText for table in result.tables]
                warnings = list(result.warnings)
                extra = {
                    "fallback_reason": result.fallbackReason,
                    "table_sources": [table.sourceName for table in result.tables],
                }
            else:
                import cv2
                import numpy as np

                image = cv2.imdecode(
                    np.frombuffer(imageBytes, dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
                if image is None:
                    raise ValueError("failed to decode comparison image")
                textParts: List[str] = []
                for result in engine.predict(image):
                    payload = self._ReadPaddleResultPayload(result)
                    markdownText = self._ReadPaddleMarkdownText(result)
                    if markdownText:
                        textParts.append(markdownText)
                    for block in payload.get("parsing_res_list", []) or []:
                        if not isinstance(block, dict):
                            continue
                        content = block.get("block_content")
                        if not isinstance(content, str) or not content.strip():
                            continue
                        if not markdownText:
                            textParts.append(content.strip())
                        if block.get("block_label") == "table":
                            tableTexts.append(content.strip())
                text = "\n\n".join(textParts)
        except Exception as error:
            return {
                "status": "error",
                "elapsed_seconds": round(perf_counter() - startedAt, 3),
                "text_length": 0,
                "table_count": 0,
                "text_preview": "",
                "text": "",
                "table_texts": [],
                "warnings": [],
                "error": str(error),
            }
        comparisonResult = {
            "status": "ok",
            "elapsed_seconds": round(perf_counter() - startedAt, 3),
            "text_length": len(text),
            "line_count": len([line for line in text.splitlines() if line.strip()]),
            "table_count": len(tableTexts),
            "text_preview": self._BuildTextPreview(
                text,
                self._ocrTextPreviewCharacters,
            ),
            "text": text,
            "table_texts": tableTexts,
            "warnings": warnings,
            "error": None,
        }
        comparisonResult.update(extra)
        return comparisonResult

    @staticmethod
    def _ReadPaddleResultPayload(result: Any) -> Dict[str, Any]:
        jsonPayload = getattr(result, "json", None)
        payload = jsonPayload if isinstance(jsonPayload, dict) else result
        if not isinstance(payload, dict):
            return {}
        nestedPayload = payload.get("res")
        return nestedPayload if isinstance(nestedPayload, dict) else payload

    @staticmethod
    def _ReadPaddleMarkdownText(result: Any) -> str:
        markdown = getattr(result, "markdown", None)
        if not isinstance(markdown, dict):
            return ""
        markdownText = markdown.get("markdown_texts")
        return markdownText.strip() if isinstance(markdownText, str) else ""

    @staticmethod
    def _IsParseOk(
        collectionResult: Dict[str, Any],
        parsedProductPage: Dict[str, Any],
        productNoticeFieldCount: int,
    ) -> bool:
        return (
            parsedProductPage["product_name"] is not None
            and collectionResult["product_notice_text_line_count"] > 0
            and productNoticeFieldCount > 0
        )

    def _LogOne(self, resultData: Dict[str, Any]) -> None:
        smokeLogger = self._Logger("_LogOne")
        statusData = resultData["status"]
        if "runtime_error" in statusData:
            smokeLogger.error(
                "url={} runtime_error={}",
                resultData["product_page_url"],
                statusData["runtime_error"],
            )
            return

        self._LogPipelineSteps(resultData)
        productData = resultData["product"]
        noticeData = resultData["raw_collection"]["notice"]
        smokeLogger.info(
            "url={} product_name={} domain={} parse_ok={} ocr_fallback_ok={}",
            resultData["product_page_url"],
            productData["product_name"],
            productData["product_domain"],
            statusData["is_parse_ok"],
            statusData["is_ocr_fallback_ok"],
        )
        smokeLogger.info(
            "brand_name={} package_type={} sale_unit={}",
            productData["brand_name"],
            productData["package_type"],
            productData["sale_unit"],
        )
        smokeLogger.info(
            (
                "notice_lines={} notice_options={} "
                "notice_fields={} requires_ocr_fallback={} "
                "image_reference_detected={}"
            ),
            noticeData["line_count"],
            noticeData["option_count"],
            noticeData["field_count"],
            noticeData["requires_ocr_fallback"],
            noticeData["image_reference_detected"],
        )
        self._LogNoticeOptions(resultData)
        self._LogOcrSummary(resultData)
        self._LogInputReconstruction(resultData)
        self._LogWarningsAndErrors(resultData)

    def _LogPipelineSteps(self, resultData: Dict[str, Any]) -> None:
        stepLogger = self._Logger("_LogPipelineSteps")
        for pipelineStep in resultData["pipeline_steps"]:
            stepLogger.info(
                "pipeline_step name={} succeeded={} message={}",
                pipelineStep["step_name"],
                pipelineStep["succeeded"],
                pipelineStep["message"],
            )

    def _LogNoticeOptions(self, resultData: Dict[str, Any]) -> None:
        noticeLogger = self._Logger("_LogNoticeOptions")
        noticeData = resultData["raw_collection"]["notice"]
        optionNames = noticeData["option_names"]
        if optionNames:
            noticeLogger.info("notice_option_names={}", optionNames)

        for noticeOption in noticeData["options_preview"]:
            noticeLogger.info(
                "notice_option index={} option_name={} field_count={}",
                noticeOption["index"],
                noticeOption["option_name"],
                noticeOption["field_count"],
            )
            for fieldRecord in noticeOption["fields_preview"]:
                noticeLogger.info(
                    (
                        "notice_option_field index={} name={} value={} "
                        "requires_ocr_fallback={}"
                    ),
                    noticeOption["index"],
                    fieldRecord["field_name"],
                    fieldRecord["field_value"],
                    fieldRecord["requires_ocr_fallback"],
                )

    def _LogInputReconstruction(self, resultData: Dict[str, Any]) -> None:
        reconstructionLogger = self._Logger("_LogInputReconstruction")
        inputReconstruction = resultData.get("llm_reconstruction", {})
        if not isinstance(inputReconstruction, dict) or not inputReconstruction:
            return
        reconstructionLogger.info(
            (
                "llm_reconstruction method={} facts={} tables={} unresolved={} "
                "conflicts={} used_llm={} fallback_reason={}"
            ),
            inputReconstruction.get("method"),
            len(inputReconstruction.get("facts", []) or []),
            len(inputReconstruction.get("reconstructed_tables", []) or []),
            len(inputReconstruction.get("unresolved_facts", []) or []),
            len(inputReconstruction.get("conflicts", []) or []),
            inputReconstruction.get("used_llm_reconstruction"),
            inputReconstruction.get("fallback_reason"),
        )
        for factRecord in inputReconstruction.get("facts", []) or []:
            reconstructionLogger.info(
                "llm_fact field={} raw={} reconstructed={} status={}",
                factRecord.get("field_name"),
                factRecord.get("raw_evidence_value"),
                factRecord.get("reconstructed_value"),
                factRecord.get("validation_status"),
            )
        for tableRecord in inputReconstruction.get("reconstructed_tables", []) or []:
            reconstructionLogger.info(
                "llm_table name={} row_count={} source_refs={}",
                tableRecord.get("table_name"),
                len(tableRecord.get("rows", []) or []),
                tableRecord.get("source_refs", []),
            )

    def _LogOcrSummary(self, resultData: Dict[str, Any]) -> None:
        ocrLogger = self._Logger("_LogOcrSummary")
        ocrData = resultData["raw_collection"]["ocr_evidence"]
        ocrLogger.info(
            (
                "detail_image_count={} ocr_candidate_count={} "
                "ocr_result_count={} successful_ocr_count={} "
                "structured_table_image_count={} structured_table_count={} "
                "raw_tile_text_count={} raw_text_length={} "
                "combined_ocr_text_length={}"
            ),
            ocrData["product_detail_image_url_count"],
            ocrData["candidate_image_url_count"],
            ocrData["image_result_count"],
            ocrData["successful_image_count"],
            ocrData["structured_table_image_count"],
            ocrData["structured_table_count"],
            ocrData["raw_tile_text_count"],
            ocrData["raw_text_length"],
            ocrData["combined_text_length"],
        )

        for imageUrl in ocrData["candidate_image_urls_preview"]:
            ocrLogger.info("ocr_candidate_image_url={}", imageUrl)

        for imageResult in ocrData["image_artifacts"]:
            ocrLogger.info(
                (
                    "ocr_image index={} image_path={} image_path_count={} text_length={} "
                    "used_structured_tables={} structured_table_count={} "
                    "raw_tile_text_count={} raw_text_length={} "
                    "merge_mode={} fallback_reason={} warning_count={} error={}"
                ),
                imageResult["index"],
                imageResult["image_path"],
                len(imageResult.get("image_paths", []) or []),
                imageResult["text_length"],
                imageResult.get("used_structured_tables", False),
                imageResult.get("structured_table_count", 0),
                imageResult.get("raw_tile_text_count", 0),
                imageResult.get("raw_text_length", 0),
                imageResult.get("text_merge_mode"),
                imageResult.get("structured_fallback_reason"),
                len(imageResult.get("structured_warnings", []) or []),
                imageResult["error"],
            )
            for warning in imageResult.get("structured_warnings", []) or []:
                ocrLogger.info(
                    "ocr_image index={} structured_warning={}",
                    imageResult["index"],
                    warning,
                )
        combinedOcrText = ocrData.get("combined_ocr_text", "")
        if combinedOcrText:
            ocrLogger.info(
                "combined_ocr_text_preview={}",
                self._BuildTextPreview(
                    combinedOcrText,
                    self._ocrTextPreviewCharacters,
                ),
            )

    def _LogWarningsAndErrors(self, resultData: Dict[str, Any]) -> None:
        eventLogger = self._Logger("_LogWarningsAndErrors")
        for warning in resultData["warnings"]:
            eventLogger.warning("warning={}", warning)
        for error in resultData["errors"]:
            eventLogger.error("error={}", error)

    def _LogSummary(self, results: List[Dict[str, Any]]) -> None:
        summaryLogger = self._Logger("_LogSummary")
        parseOkCount = sum(
            1 for result in results if result["status"].get("is_parse_ok")
        )
        ocrOkCount = sum(
            1 for result in results if result["status"].get("is_ocr_fallback_ok")
        )
        summaryLogger.info(
            "summary parse_ok={}/{} ocr_fallback_ok={}/{}",
            parseOkCount,
            len(results),
            ocrOkCount,
            len(results),
        )
        if self._logFullResult:
            summaryLogger.info(
                "\n{}",
                json.dumps(results, ensure_ascii=False, indent=2),
            )

    def _WriteSummaryArtifact(self, results: List[Dict[str, Any]]) -> None:
        self._summaryArtifactPath.parent.mkdir(parents=True, exist_ok=True)
        self._summaryArtifactPath.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._Logger("_WriteSummaryArtifact").info(
            "summary_artifact_path={}",
            self._summaryArtifactPath,
        )

    def _BuildInputReconstructionView(
        self,
        inputReconstruction: Dict[str, Any],
    ) -> Dict[str, Any]:
        facts = [
            self._BuildReconstructedFactView(factRecord)
            for factRecord in inputReconstruction.get("product_facts", []) or []
            if isinstance(factRecord, dict)
        ]
        unresolvedFacts = [
            self._BuildReconstructedFactView(factRecord)
            for factRecord in inputReconstruction.get("unresolved_facts", []) or []
            if isinstance(factRecord, dict)
        ]
        usedLlmReconstruction = bool(
            inputReconstruction.get("used_llm_reconstruction"),
        )
        if usedLlmReconstruction:
            method = "llm"
        elif facts:
            method = "deterministic"
        else:
            method = "none"

        return {
            "method": method,
            "used_llm_reconstruction": usedLlmReconstruction,
            "fallback_reason": inputReconstruction.get("fallback_reason"),
            "facts": facts,
            "reconstructed_tables": inputReconstruction.get(
                "reconstructed_tables",
                [],
            )
            or [],
            "unresolved_facts": unresolvedFacts,
            "conflicts": inputReconstruction.get("conflicts", []) or [],
            "fact_texts_for_classification": inputReconstruction.get(
                "normalized_fact_texts",
                [],
            )
            or [],
            "warnings": inputReconstruction.get("warnings", []) or [],
            "debug_artifacts": inputReconstruction.get("debug_artifacts", {}) or {},
        }

    @staticmethod
    def _BuildReconstructedFactView(
        factRecord: Dict[str, Any],
    ) -> Dict[str, Any]:
        rawValue = factRecord.get("raw_value") or ""
        reconstructedValue = factRecord.get("normalized_value") or rawValue
        return {
            "field_name": factRecord.get("field_name"),
            "raw_evidence_value": rawValue,
            "reconstructed_value": reconstructedValue,
            "source_refs": factRecord.get("source_refs", []) or [],
            "reconstruction_type": factRecord.get("correction_type"),
            "validation_status": factRecord.get("validation_status"),
        }

    @staticmethod
    def _BuildTextPreview(text: Any, maxCharacters: int) -> Any:
        if not isinstance(text, str):
            return text
        if len(text) <= maxCharacters:
            return text
        return "{0}...".format(text[:maxCharacters])

    def _BuildOptionPreview(
        self,
        noticeOptions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        optionPreview: List[Dict[str, Any]] = []
        for optionIndex, noticeOption in enumerate(
            noticeOptions[:self._maxLoggedNoticeOptions],
            start=1,
        ):
            optionPreview.append(
                {
                    "index": optionIndex,
                    "option_name": noticeOption["option_name"],
                    "field_count": len(noticeOption["fields"]),
                    "fields_preview": [
                        self._BuildFieldRecordPreview(fieldRecord)
                        for fieldRecord in noticeOption["fields"][
                            :self._maxLoggedFieldsPerOption
                        ]
                    ],
                }
            )
        return optionPreview

    @staticmethod
    def _CountNoticeOptionFields(
        noticeOptions: List[Dict[str, Any]],
    ) -> int:
        seenFieldKeys = set()
        for noticeOption in noticeOptions:
            fields = noticeOption.get("fields", [])
            if not isinstance(fields, list):
                continue
            for fieldRecord in fields:
                if not isinstance(fieldRecord, dict):
                    continue
                seenFieldKeys.add(
                    (
                        fieldRecord.get("field_name"),
                        fieldRecord.get("field_value"),
                    )
                )
        return len(seenFieldKeys)

    def _BuildFieldRecordPreview(
        self,
        fieldRecord: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "field_name": fieldRecord["field_name"],
            "field_value": self._BuildTextPreview(
                fieldRecord["field_value"],
                self._fieldValuePreviewCharacters,
            ),
            "requires_ocr_fallback": fieldRecord["requires_ocr_fallback"],
        }

    @staticmethod
    def _ConfigureLogger() -> None:
        logger.remove()
        logger.level("INFO", color="<green>")
        logger.level("WARNING", color="<yellow>")
        logger.level("ERROR", color="<red>")
        logger.configure(
            extra={
                "className": "KurlyMarketSmokeRunner",
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
    cliArguments = ParseArguments()
    KurlyMarketSmokeRunner(
        showBrowser=cliArguments.headed,
        compareOcr=cliArguments.compare_ocr,
        compareMaxImages=cliArguments.compare_max_images,
    ).Run()
