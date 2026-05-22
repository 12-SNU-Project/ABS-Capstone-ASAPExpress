"""Kurly Market 여러 상품 URL의 parser/OCR fallback runtime smoke."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger


PROJECT_ROOT_PATH = Path(__file__).resolve().parent
SOURCE_ROOT_PATH = PROJECT_ROOT_PATH / "src"
if str(SOURCE_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT_PATH))

from eu_export import (
    KurlyMarketProductPageCollector,
    KurlyMarketProductSourcePipeline,
    KurlyMarketProductSourcePipelineInput,
    PaddleOcrEngine,
)


DEFAULT_PRODUCT_URLS = [
    "https://www.kurly.com/goods/5037259",
    "https://www.kurly.com/goods/1000319181",
    "https://www.kurly.com/goods/1001109031",
    "https://www.kurly.com/goods/1002127593",
]
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_SCROLL_COUNT = 8
DEFAULT_HEADLESS = True
DEFAULT_MAX_OCR_IMAGE_COUNT = 8
DEFAULT_ARTIFACT_ROOT_PATH = PROJECT_ROOT_PATH / "artifacts" / "kurly-market-ocr"
DEFAULT_SUMMARY_ARTIFACT_PATH = (
    DEFAULT_ARTIFACT_ROOT_PATH / "runtime-smoke-summary.json"
)
DEFAULT_OCR_TEXT_PREVIEW_CHARACTERS = 500


class KurlyMarketMultiUrlSmokeRunner:
    """여러 Kurly Market 상품 URL을 실제 런타임으로 검증한다."""

    def Run(self) -> None:
        self._ConfigureLogger()
        runLogger = self._Logger("Run")
        runLogger.info("starting multi URL runtime smoke count={}", len(DEFAULT_PRODUCT_URLS))

        collector = KurlyMarketProductPageCollector(
            headless=DEFAULT_HEADLESS,
            timeoutMilliseconds=DEFAULT_TIMEOUT_SECONDS * 1000,
            scrollCount=DEFAULT_SCROLL_COUNT,
        )
        ocrEngine = PaddleOcrEngine()
        productSourcePipeline = KurlyMarketProductSourcePipeline(
            collector=collector,
            ocrEngine=ocrEngine,
        )

        results: List[Dict[str, Any]] = []
        for productUrl in DEFAULT_PRODUCT_URLS:
            resultData = self._RunOne(productSourcePipeline, productUrl)
            results.append(resultData)
            self._LogOne(resultData)

        self._LogSummary(results)
        self._WriteSummaryArtifact(results)

    def _RunOne(
        self,
        productSourcePipeline: KurlyMarketProductSourcePipeline,
        productUrl: str,
    ) -> Dict[str, Any]:
        try:
            pipelineResult = productSourcePipeline.Run(
                KurlyMarketProductSourcePipelineInput(
                    productPageUrl=productUrl,
                    runOcrFallback=True,
                    artifactRootPath=DEFAULT_ARTIFACT_ROOT_PATH,
                    maxOcrImageCount=DEFAULT_MAX_OCR_IMAGE_COUNT,
                )
            )
            return self._BuildResult(productUrl, pipelineResult.ToDict())
        except Exception as error:
            return {
                "product_page_url": productUrl,
                "runtime_error": str(error),
                "is_parse_ok": False,
                "is_ocr_fallback_ok": False,
            }

    def _BuildResult(
        self,
        productUrl: str,
        pipelineResultData: Dict[str, Any],
    ) -> Dict[str, Any]:
        collectionResult = pipelineResultData["collection_result"]
        parsedProductPage = collectionResult["parsed_product_page"]
        ocrImageResults = pipelineResultData["ocr_image_results"]
        combinedOcrText = pipelineResultData["combined_ocr_text"]
        requiresOcrFallback = parsedProductPage["requires_ocr_fallback"]

        successfulOcrResults = [
            imageResult
            for imageResult in ocrImageResults
            if imageResult["error"] is None and len(imageResult["ocr_text"]) > 0
        ]
        isOcrFallbackOk = (
            not requiresOcrFallback
            or len(successfulOcrResults) > 0
        )

        return {
            "product_page_url": productUrl,
            "product_name": parsedProductPage["product_name"],
            "product_domain": parsedProductPage["product_domain"],
            "product_notice_text_line_count": collectionResult[
                "product_notice_text_line_count"
            ],
            "product_notice_field_count": len(
                parsedProductPage["product_notice_fields"]
            ),
            "product_notice_option_count": len(
                parsedProductPage["product_notice_options"]
            ),
            "requires_ocr_fallback": requiresOcrFallback,
            "image_reference_detected": parsedProductPage[
                "image_reference_detected"
            ],
            "product_detail_image_url_count": len(
                collectionResult["product_detail_image_urls"]
            ),
            "ocr_candidate_image_url_count": len(
                collectionResult["ocr_candidate_image_urls"]
            ),
            "ocr_image_result_count": len(ocrImageResults),
            "successful_ocr_image_count": len(successfulOcrResults),
            "combined_ocr_text_length": len(combinedOcrText),
            "combined_ocr_text_preview": self._BuildTextPreview(combinedOcrText),
            "is_parse_ok": (
                parsedProductPage["product_name"] is not None
                and collectionResult["product_notice_text_line_count"] > 0
                and len(parsedProductPage["product_notice_fields"]) > 0
            ),
            "is_ocr_fallback_ok": isOcrFallbackOk,
            "pipeline_steps": pipelineResultData["steps"],
            "warnings": collectionResult["warnings"],
            "errors": pipelineResultData["errors"],
        }

    def _LogOne(self, resultData: Dict[str, Any]) -> None:
        smokeLogger = self._Logger("_LogOne")
        if "runtime_error" in resultData:
            smokeLogger.error(
                "url={} runtime_error={}",
                resultData["product_page_url"],
                resultData["runtime_error"],
            )
            return

        smokeLogger.info(
            (
                "url={} product_name={} domain={} "
                "parse_ok={} ocr_fallback_ok={}"
            ),
            resultData["product_page_url"],
            resultData["product_name"],
            resultData["product_domain"],
            resultData["is_parse_ok"],
            resultData["is_ocr_fallback_ok"],
        )
        smokeLogger.info(
            (
                "notice_lines={} notice_fields={} notice_options={} "
                "requires_ocr_fallback={}"
            ),
            resultData["product_notice_text_line_count"],
            resultData["product_notice_field_count"],
            resultData["product_notice_option_count"],
            resultData["requires_ocr_fallback"],
        )
        smokeLogger.info(
            (
                "detail_image_count={} ocr_candidate_count={} "
                "ocr_result_count={} successful_ocr_count={} "
                "combined_ocr_text_length={}"
            ),
            resultData["product_detail_image_url_count"],
            resultData["ocr_candidate_image_url_count"],
            resultData["ocr_image_result_count"],
            resultData["successful_ocr_image_count"],
            resultData["combined_ocr_text_length"],
        )
        smokeLogger.info(
            "ocr_text_preview={}",
            resultData["combined_ocr_text_preview"],
        )

        for warning in resultData["warnings"]:
            smokeLogger.warning("warning={}", warning)
        for error in resultData["errors"]:
            smokeLogger.error("error={}", error)

    def _LogSummary(self, results: List[Dict[str, Any]]) -> None:
        summaryLogger = self._Logger("_LogSummary")
        parseOkCount = sum(1 for result in results if result.get("is_parse_ok"))
        ocrOkCount = sum(1 for result in results if result.get("is_ocr_fallback_ok"))
        summaryLogger.info(
            "summary parse_ok={}/{} ocr_fallback_ok={}/{}",
            parseOkCount,
            len(results),
            ocrOkCount,
            len(results),
        )
        summaryLogger.info(
            "\n{}",
            json.dumps(results, ensure_ascii=False, indent=2),
        )

    def _WriteSummaryArtifact(self, results: List[Dict[str, Any]]) -> None:
        DEFAULT_SUMMARY_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_SUMMARY_ARTIFACT_PATH.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._Logger("_WriteSummaryArtifact").info(
            "summary_artifact_path={}",
            DEFAULT_SUMMARY_ARTIFACT_PATH,
        )

    def _BuildTextPreview(self, text: str) -> str:
        if len(text) <= DEFAULT_OCR_TEXT_PREVIEW_CHARACTERS:
            return text
        return "{0}...".format(text[:DEFAULT_OCR_TEXT_PREVIEW_CHARACTERS])

    def _ConfigureLogger(self) -> None:
        logger.remove()
        logger.configure(
            extra={
                "className": "KurlyMarketMultiUrlSmokeRunner",
                "functionName": "Run",
            }
        )
        logger.add(
            sys.stderr,
            format="[{level}] {extra[className]}::{extra[functionName]}: {message}",
            level="INFO",
        )

    def _Logger(self, functionName: str) -> Any:
        return logger.bind(
            className=self.__class__.__name__,
            functionName=functionName,
        )


if __name__ == "__main__":
    KurlyMarketMultiUrlSmokeRunner().Run()
