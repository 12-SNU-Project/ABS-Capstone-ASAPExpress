"""KurlyMarket 상품 페이지 parser/OCR fallback runtime smoke."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger


PROJECT_ROOT_PATH = Path(__file__).resolve().parent
SOURCE_ROOT_PATH = PROJECT_ROOT_PATH / "src"
if str(SOURCE_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT_PATH))

from eu_export.product import (  # noqa: E402
    KurlyMarketProductPageCollector,
    KurlyMarketProductSourcePipeline,
    KurlyMarketProductSourcePipelineInput,
    PaddleOcrEngine,
)


DEFAULT_PRODUCT_URLS = [
    """여기에 링크 추가하셈."""
]

DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_SCROLL_COUNT = 8
DEFAULT_HEADLESS = True
DEFAULT_RUN_OCR_FALLBACK = True
DEFAULT_MAX_OCR_IMAGE_COUNT = 8
DEFAULT_WRITE_SUMMARY_ARTIFACT = True
DEFAULT_LOG_FULL_RESULT = False
DEFAULT_ARTIFACT_ROOT_PATH = PROJECT_ROOT_PATH / "artifacts" / "kurly-market-smoke"
DEFAULT_SUMMARY_ARTIFACT_PATH = (
    DEFAULT_ARTIFACT_ROOT_PATH / "runtime-smoke-summary.json"
)
DEFAULT_MAX_LOGGED_NOTICE_OPTIONS = 3
DEFAULT_MAX_LOGGED_FIELDS_PER_OPTION = 5
DEFAULT_MAX_LOGGED_OCR_CANDIDATE_URLS = 5
DEFAULT_FIELD_VALUE_PREVIEW_CHARACTERS = 220
DEFAULT_OCR_TEXT_PREVIEW_CHARACTERS = 500


class KurlyMarketSmokeRunner:
    """실제 KurlyMarket URL에서 parser와 선택적 OCR fallback을 확인한다."""

    def Run(self) -> None:
        self._ConfigureLogger()
        runLogger = self._Logger("Run")
        runLogger.info(
            "KurlyMarket 상품 수집 smoke를 시작합니다 url_count={} run_ocr_fallback={}",
            len(DEFAULT_PRODUCT_URLS),
            DEFAULT_RUN_OCR_FALLBACK,
        )

        runLogger.info("STEP 1/4 상품 페이지 수집/OCR 파이프라인을 준비합니다")
        productSourcePipeline = self._BuildProductSourcePipeline()

        runLogger.info(
            "STEP 2/4 KurlyMarket 상품 페이지를 수집합니다 url_count={}",
            len(DEFAULT_PRODUCT_URLS),
        )
        results: List[Dict[str, Any]] = []
        for productIndex, productUrl in enumerate(DEFAULT_PRODUCT_URLS, start=1):
            runLogger.info(
                "STEP 2/4 상품 페이지 수집 index={}/{} url={}",
                productIndex,
                len(DEFAULT_PRODUCT_URLS),
                productUrl,
            )
            resultData = self._RunOne(productSourcePipeline, productUrl)
            results.append(resultData)
            self._LogOne(resultData)

        runLogger.info("STEP 3/4 상품 수집 결과를 요약합니다")
        self._LogSummary(results)
        if DEFAULT_WRITE_SUMMARY_ARTIFACT:
            runLogger.info("STEP 4/4 상품 수집 결과 JSON artifact를 저장합니다")
            self._WriteSummaryArtifact(results)
        else:
            runLogger.info("STEP 4/4 상품 수집 결과 JSON artifact 저장을 건너뜁니다")

    def _BuildProductSourcePipeline(self) -> KurlyMarketProductSourcePipeline:
        collector = KurlyMarketProductPageCollector(
            headless=DEFAULT_HEADLESS,
            timeoutMilliseconds=DEFAULT_TIMEOUT_SECONDS * 1000,
            scrollCount=DEFAULT_SCROLL_COUNT,
        )
        if not DEFAULT_RUN_OCR_FALLBACK:
            return KurlyMarketProductSourcePipeline(collector=collector)

        return KurlyMarketProductSourcePipeline(
            collector=collector,
            ocrEngine=PaddleOcrEngine(),
        )

    def _RunOne(
        self,
        productSourcePipeline: KurlyMarketProductSourcePipeline,
        productUrl: str,
    ) -> Dict[str, Any]:
        try:
            pipelineResult = productSourcePipeline.Run(
                KurlyMarketProductSourcePipelineInput(
                    productPageUrl=productUrl,
                    runOcrFallback=DEFAULT_RUN_OCR_FALLBACK,
                    artifactRootPath=DEFAULT_ARTIFACT_ROOT_PATH,
                    maxOcrImageCount=DEFAULT_MAX_OCR_IMAGE_COUNT,
                )
            )
            return self._BuildResult(productUrl, pipelineResult.ToDict())
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
        ocrImageResults = pipelineResultData.get("ocr_image_results", [])
        combinedOcrText = pipelineResultData["combined_ocr_text"]
        requiresOcrFallback = parsedProductPage["requires_ocr_fallback"]

        successfulOcrResults = [
            imageResult
            for imageResult in ocrImageResults
            if imageResult["error"] is None and len(imageResult["ocr_text"]) > 0
        ]
        successfulOcrImageCount = int(
            ocrSummary.get("successful_image_count", len(successfulOcrResults)),
        )
        isOcrFallbackOk = (
            not requiresOcrFallback
            or (
                DEFAULT_RUN_OCR_FALLBACK
                and successfulOcrImageCount > 0
            )
        )

        return {
            "product_page_url": productUrl,
            "parsed_product_page": parsedProductPage,
            "collection_summary": collectionResult,
            "rendered_page_evidence_summary": pipelineResultData.get(
                "rendered_page_evidence_summary",
            ),
            "ocr_summary": ocrSummary,
            "combined_ocr_text": combinedOcrText,
            "steps": pipelineResultData["steps"],
            "status": {
                "is_parse_ok": self._IsParseOk(collectionResult, parsedProductPage),
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
            "notice": {
                "line_count": collectionResult["product_notice_text_line_count"],
                "field_count": len(parsedProductPage["product_notice_fields"]),
                "option_count": len(parsedProductPage["product_notice_options"]),
                "option_names": parsedProductPage["product_notice_option_names"],
                "fields_preview": self._BuildFieldPreview(
                    parsedProductPage["product_notice_fields"],
                ),
                "options_preview": self._BuildOptionPreview(
                    parsedProductPage["product_notice_options"],
                ),
                "requires_ocr_fallback": requiresOcrFallback,
                "image_reference_detected": parsedProductPage[
                    "image_reference_detected"
                ],
            },
            "ocr": {
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
                )[:DEFAULT_MAX_LOGGED_OCR_CANDIDATE_URLS],
                "image_result_count": ocrSummary.get(
                    "image_result_count",
                    len(ocrImageResults),
                ),
                "successful_image_count": ocrSummary.get(
                    "successful_image_count",
                    len(successfulOcrResults),
                ),
                "image_artifacts": ocrSummary.get(
                    "image_artifacts",
                    self._BuildOcrImageArtifacts(ocrImageResults),
                ),
                "combined_text_length": len(combinedOcrText),
                "combined_text_preview": self._BuildTextPreview(
                    combinedOcrText,
                    DEFAULT_OCR_TEXT_PREVIEW_CHARACTERS,
                ),
            },
            "pipeline_steps": pipelineResultData["steps"],
            "warnings": collectionResult["warnings"],
            "errors": pipelineResultData["errors"],
        }

    def _IsParseOk(
        self,
        collectionResult: Dict[str, Any],
        parsedProductPage: Dict[str, Any],
    ) -> bool:
        return (
            parsedProductPage["product_name"] is not None
            and collectionResult["product_notice_text_line_count"] > 0
            and len(parsedProductPage["product_notice_fields"]) > 0
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
        noticeData = resultData["notice"]
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
        self._LogNoticeFields(resultData)
        self._LogOcrSummary(resultData)
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
        noticeData = resultData["notice"]
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

    def _LogNoticeFields(self, resultData: Dict[str, Any]) -> None:
        noticeLogger = self._Logger("_LogNoticeFields")
        for fieldRecord in resultData["notice"]["fields_preview"]:
            noticeLogger.info(
                "notice_field name={} value={} requires_ocr_fallback={}",
                fieldRecord["field_name"],
                fieldRecord["field_value"],
                fieldRecord["requires_ocr_fallback"],
            )

    def _LogOcrSummary(self, resultData: Dict[str, Any]) -> None:
        ocrLogger = self._Logger("_LogOcrSummary")
        ocrData = resultData["ocr"]
        ocrLogger.info(
            (
                "detail_image_count={} ocr_candidate_count={} "
                "ocr_result_count={} successful_ocr_count={} "
                "combined_ocr_text_length={}"
            ),
            ocrData["product_detail_image_url_count"],
            ocrData["candidate_image_url_count"],
            ocrData["image_result_count"],
            ocrData["successful_image_count"],
            ocrData["combined_text_length"],
        )

        for imageUrl in ocrData["candidate_image_urls_preview"]:
            ocrLogger.info("ocr_candidate_image_url={}", imageUrl)

        for imageResult in ocrData["image_artifacts"]:
            ocrLogger.info(
                "ocr_image index={} image_path={} text_length={} error={}",
                imageResult["index"],
                imageResult["image_path"],
                imageResult["text_length"],
                imageResult["error"],
            )

        if ocrData["combined_text_preview"]:
            ocrLogger.info(
                "combined_ocr_text_preview={}",
                ocrData["combined_text_preview"],
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
        if DEFAULT_LOG_FULL_RESULT:
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

    def _BuildTextPreview(self, text: Any, maxCharacters: int) -> Any:
        if not isinstance(text, str):
            return text
        if len(text) <= maxCharacters:
            return text
        return "{0}...".format(text[:maxCharacters])

    def _BuildFieldPreview(
        self,
        fieldRecords: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return [
            self._BuildFieldRecordPreview(fieldRecord)
            for fieldRecord in fieldRecords[:DEFAULT_MAX_LOGGED_FIELDS_PER_OPTION]
        ]

    def _BuildOptionPreview(
        self,
        noticeOptions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        optionPreview: List[Dict[str, Any]] = []
        for optionIndex, noticeOption in enumerate(
            noticeOptions[:DEFAULT_MAX_LOGGED_NOTICE_OPTIONS],
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
                            :DEFAULT_MAX_LOGGED_FIELDS_PER_OPTION
                        ]
                    ],
                }
            )
        return optionPreview

    def _BuildFieldRecordPreview(
        self,
        fieldRecord: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "field_name": fieldRecord["field_name"],
            "field_value": self._BuildTextPreview(
                fieldRecord["field_value"],
                DEFAULT_FIELD_VALUE_PREVIEW_CHARACTERS,
            ),
            "requires_ocr_fallback": fieldRecord["requires_ocr_fallback"],
        }

    def _BuildOcrImageArtifacts(
        self,
        ocrImageResults: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return [
            {
                "index": imageIndex,
                "image_path": imageResult["image_path"],
                "text_length": len(imageResult["ocr_text"]),
                "error": imageResult["error"],
            }
            for imageIndex, imageResult in enumerate(ocrImageResults, start=1)
        ]

    def _ConfigureLogger(self) -> None:
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
    KurlyMarketSmokeRunner().Run()
