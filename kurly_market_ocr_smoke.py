"""KurlyMarket 상품 페이지 수집 후 PaddleOCR fallback까지 확인하는 smoke flow."""

import json
import sys
from pathlib import Path
from typing import Any, Dict

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


DEFAULT_PRODUCT_URL = "https://www.kurly.com/goods/5037259?collectionCode=2605-brthweek-home-01"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_SCROLL_COUNT = 8
DEFAULT_HEADLESS = True
DEFAULT_MAX_OCR_IMAGE_COUNT = 1
DEFAULT_ARTIFACT_ROOT_PATH = PROJECT_ROOT_PATH / "artifacts" / "beauty-kurly-ocr"
DEFAULT_LOG_FULL_RESULT = False
DEFAULT_OCR_TEXT_PREVIEW_CHARACTERS = 1000


class KurlyMarketOcrSmokeRunner:
    """실제 Kurly URL에서 상품고시정보와 OCR fallback 연결을 확인한다."""

    def Run(self) -> None:
        self._ConfigureLogger()
        runLogger = self._Logger("Run")
        runLogger.info(
            "collecting KurlyMarket product page with OCR url={}",
            DEFAULT_PRODUCT_URL,
        )

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
        pipelineResult = productSourcePipeline.Run(
            KurlyMarketProductSourcePipelineInput(
                productPageUrl=DEFAULT_PRODUCT_URL,
                runOcrFallback=True,
                artifactRootPath=DEFAULT_ARTIFACT_ROOT_PATH,
                maxOcrImageCount=DEFAULT_MAX_OCR_IMAGE_COUNT,
            )
        )
        resultData = self._BuildResult(pipelineResult.ToDict())

        self._LogCoreResult(resultData)
        if DEFAULT_LOG_FULL_RESULT:
            runLogger.info("full OCR smoke result follows")
            runLogger.info(
                "\n{}",
                json.dumps(resultData, ensure_ascii=False, indent=2),
            )

    def _ConfigureLogger(self) -> None:
        logger.remove()
        logger.configure(
            extra={
                "className": "KurlyMarketOcrSmokeRunner",
                "functionName": "Run",
            }
        )
        logger.add(
            sys.stderr,
            format="[{level}] {extra[className]}::{extra[functionName]}: {message}",
            level="INFO",
        )

    def _BuildResult(self, pipelineResultData: Dict[str, Any]) -> Dict[str, Any]:
        collectionResult = pipelineResultData["collection_result"]
        parsedProductPage = collectionResult["parsed_product_page"]
        ocrImageResults = pipelineResultData["ocr_image_results"]
        combinedOcrText = pipelineResultData["combined_ocr_text"]

        return {
            "product_page_url": collectionResult["product_page_url"],
            "product_domain": parsedProductPage["product_domain"],
            "product_name": parsedProductPage["product_name"],
            "product_notice_text_line_count": collectionResult[
                "product_notice_text_line_count"
            ],
            "product_notice_field_count": len(
                parsedProductPage["product_notice_fields"]
            ),
            "requires_ocr_fallback": parsedProductPage[
                "requires_ocr_fallback"
            ],
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
            "ocr_image_results": ocrImageResults,
            "combined_ocr_text_length": len(combinedOcrText),
            "combined_ocr_text_preview": self._BuildTextPreview(combinedOcrText),
            "pipeline_steps": pipelineResultData["steps"],
            "errors": pipelineResultData["errors"],
            "warnings": collectionResult["warnings"],
        }

    def _LogCoreResult(self, resultData: Dict[str, Any]) -> None:
        coreLogger = self._Logger("_LogCoreResult")
        for pipelineStep in resultData["pipeline_steps"]:
            coreLogger.info(
                "pipeline_step name={} succeeded={} message={}",
                pipelineStep["step_name"],
                pipelineStep["succeeded"],
                pipelineStep["message"],
            )

        coreLogger.info("product_name={}", resultData["product_name"])
        coreLogger.info("product_domain={}", resultData["product_domain"])
        coreLogger.info(
            (
                "notice_line_count={}, notice_field_count={}, "
                "requires_ocr_fallback={}, image_reference_detected={}"
            ),
            resultData["product_notice_text_line_count"],
            resultData["product_notice_field_count"],
            resultData["requires_ocr_fallback"],
            resultData["image_reference_detected"],
        )
        coreLogger.info(
            (
                "product_detail_image_url_count={}, "
                "ocr_candidate_image_url_count={}, "
                "ocr_image_result_count={}"
            ),
            resultData["product_detail_image_url_count"],
            resultData["ocr_candidate_image_url_count"],
            resultData["ocr_image_result_count"],
        )

        for imageIndex, imageResult in enumerate(
            resultData["ocr_image_results"],
            start=1,
        ):
            coreLogger.info(
                (
                    "ocr_image index={} image_path={} text_length={} error={}"
                ),
                imageIndex,
                imageResult["image_path"],
                len(imageResult["ocr_text"]),
                imageResult["error"],
            )

        coreLogger.info(
            "combined_ocr_text_length={}",
            resultData["combined_ocr_text_length"],
        )
        coreLogger.info(
            "combined_ocr_text_preview={}",
            resultData["combined_ocr_text_preview"],
        )

        for warning in resultData["warnings"]:
            coreLogger.warning("warning={}", warning)
        for error in resultData["errors"]:
            coreLogger.error("error={}", error)

    def _BuildTextPreview(self, text: str) -> str:
        if len(text) <= DEFAULT_OCR_TEXT_PREVIEW_CHARACTERS:
            return text
        return "{0}...".format(text[:DEFAULT_OCR_TEXT_PREVIEW_CHARACTERS])

    def _Logger(self, functionName: str) -> Any:
        return logger.bind(
            className=self.__class__.__name__,
            functionName=functionName,
        )


if __name__ == "__main__":
    KurlyMarketOcrSmokeRunner().Run()
