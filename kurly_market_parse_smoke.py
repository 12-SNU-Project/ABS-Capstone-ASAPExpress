"""KurlyMarket 상품 페이지 파싱 smoke flow."""

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
)


DEFAULT_PRODUCT_URL = "https://www.kurly.com/goods/5037259?collectionCode=2605-brthweek-home-01"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_SCROLL_COUNT = 8
DEFAULT_HEADLESS = True
DEFAULT_LOG_FULL_RESULT = False
DEFAULT_MAX_LOGGED_NOTICE_OPTIONS = 3
DEFAULT_MAX_LOGGED_FIELDS_PER_OPTION = 5
DEFAULT_MAX_LOGGED_FIELD_VALUE_CHARACTERS = 220
DEFAULT_MAX_LOGGED_OCR_CANDIDATE_URLS = 5


class KurlyMarketParseSmokeRunner:
    """KurlyMarket 상품고시정보와 OCR 후보 이미지 URL만 확인한다."""

    def Run(self) -> None:
        self._ConfigureLogger()
        runLogger = self._Logger("Run")
        runLogger.info(
            "collecting KurlyMarket product page url={}",
            DEFAULT_PRODUCT_URL,
        )

        collector = KurlyMarketProductPageCollector(
            headless=DEFAULT_HEADLESS,
            timeoutMilliseconds=DEFAULT_TIMEOUT_SECONDS * 1000,
            scrollCount=DEFAULT_SCROLL_COUNT,
        )
        productSourcePipeline = KurlyMarketProductSourcePipeline(collector)
        pipelineResult = productSourcePipeline.Run(
            KurlyMarketProductSourcePipelineInput(
                productPageUrl=DEFAULT_PRODUCT_URL,
                runOcrFallback=False,
            )
        )
        resultData = self._BuildResult(pipelineResult.ToDict())

        self._LogCoreResult(resultData)
        if DEFAULT_LOG_FULL_RESULT:
            self._Logger("Run").info("full parse result follows")
            self._Logger("Run").info(
                "\n{}",
                json.dumps(
                    resultData,
                    ensure_ascii=False,
                    indent=2,
                ),
            )

    def _ConfigureLogger(self) -> None:
        logger.remove()
        logger.configure(
            extra={
                "className": "KurlyMarketParseSmokeRunner",
                "functionName": "Run",
            }
        )
        logger.add(
            sys.stderr,
            format="[{level}] {extra[className]}::{extra[functionName]}: {message}",
            level="INFO",
        )

    def _BuildResult(self, resultData: Dict[str, Any]) -> Dict[str, Any]:
        pipelineSteps = resultData["steps"]
        resultData = resultData["collection_result"]
        parsedProductPage = resultData["parsed_product_page"]
        noticeFields = parsedProductPage["product_notice_fields"]
        noticeGroups = parsedProductPage["product_notice_groups"]
        noticeOptions = parsedProductPage["product_notice_options"]
        ocrCandidateImageUrls = resultData["ocr_candidate_image_urls"]

        return {
            "product_page_url": resultData["product_page_url"],
            "visible_text_line_count": resultData["visible_text_line_count"],
            "product_notice_text_line_count": resultData[
                "product_notice_text_line_count"
            ],
            "product_domain": parsedProductPage["product_domain"],
            "product_name": parsedProductPage["product_name"],
            "short_description": parsedProductPage["short_description"],
            "brand_name": parsedProductPage["brand_name"],
            "package_type": parsedProductPage["package_type"],
            "sale_unit": parsedProductPage["sale_unit"],
            "product_notice": {
                "option_names": parsedProductPage[
                    "product_notice_option_names"
                ],
                "group_count": len(noticeGroups),
                "groups": noticeGroups,
                "option_record_count": len(noticeOptions),
                "options": noticeOptions,
                "field_count": len(noticeFields),
                "fields": noticeFields,
                "image_reference_detected": parsedProductPage[
                    "image_reference_detected"
                ],
                "requires_ocr_fallback": parsedProductPage[
                    "requires_ocr_fallback"
                ],
            },
            "product_detail_image_url_count": len(
                resultData["product_detail_image_urls"]
            ),
            "ocr_candidate_image_url_count": len(ocrCandidateImageUrls),
            "ocr_candidate_image_urls": ocrCandidateImageUrls,
            "pipeline_steps": pipelineSteps,
            "warnings": resultData["warnings"],
        }

    def _LogCoreResult(self, resultData: Dict[str, Any]) -> None:
        coreLogger = self._Logger("_LogCoreResult")
        productNotice = resultData["product_notice"]

        for pipelineStep in resultData["pipeline_steps"]:
            coreLogger.info(
                "pipeline_step name={} succeeded={} message={}",
                pipelineStep["step_name"],
                pipelineStep["succeeded"],
                pipelineStep["message"],
            )

        coreLogger.info("product_name={}", resultData["product_name"])
        coreLogger.info("product_domain={}", resultData["product_domain"])
        coreLogger.info("brand_name={}", resultData["brand_name"])
        coreLogger.info("package_type={}", resultData["package_type"])
        coreLogger.info("sale_unit={}", resultData["sale_unit"])
        coreLogger.info(
            (
                "product_notice_text_line_count={}, "
                "group_count={}, "
                "option_record_count={}, "
                "field_count={}, "
                "requires_ocr_fallback={}"
            ),
            resultData["product_notice_text_line_count"],
            productNotice["group_count"],
            productNotice["option_record_count"],
            productNotice["field_count"],
            productNotice["requires_ocr_fallback"],
        )

        optionNames = productNotice["option_names"]
        if optionNames:
            coreLogger.info("product_notice_options={}", optionNames)

        for groupIndex, noticeGroup in enumerate(productNotice["groups"], start=1):
            coreLogger.info(
                "notice_group index={} option_count={} field_count={}",
                groupIndex,
                len(noticeGroup["option_names"]),
                len(noticeGroup["fields"]),
            )
            if noticeGroup["option_names"]:
                coreLogger.info(
                    "notice_group_options index={} option_names={}",
                    groupIndex,
                    noticeGroup["option_names"],
                )

        for optionIndex, noticeOption in enumerate(productNotice["options"], start=1):
            coreLogger.info(
                "notice_option index={} option_name={} field_count={}",
                optionIndex,
                noticeOption["option_name"],
                len(noticeOption["fields"]),
            )
            if optionIndex > DEFAULT_MAX_LOGGED_NOTICE_OPTIONS:
                continue

            loggedFields = noticeOption["fields"][
                :DEFAULT_MAX_LOGGED_FIELDS_PER_OPTION
            ]
            for fieldRecord in loggedFields:
                coreLogger.info(
                    (
                        "notice_option_field index={} "
                        "name={} value={} requires_ocr_fallback={}"
                    ),
                    optionIndex,
                    fieldRecord["field_name"],
                    self._FormatFieldValue(fieldRecord["field_value"]),
                    fieldRecord["requires_ocr_fallback"],
                )

            remainingFieldCount = len(noticeOption["fields"]) - len(loggedFields)
            if remainingFieldCount > 0:
                coreLogger.info(
                    "notice_option_field_more index={} remaining_field_count={}",
                    optionIndex,
                    remainingFieldCount,
                )

        for fieldRecord in productNotice["fields"]:
            coreLogger.info(
                "notice_field name={} value={} requires_ocr_fallback={}",
                fieldRecord["field_name"],
                self._FormatFieldValue(fieldRecord["field_value"]),
                fieldRecord["requires_ocr_fallback"],
            )

        coreLogger.info(
            "product_detail_image_url_count={}, ocr_candidate_image_url_count={}",
            resultData["product_detail_image_url_count"],
            resultData["ocr_candidate_image_url_count"],
        )
        for imageUrl in resultData["ocr_candidate_image_urls"][
            :DEFAULT_MAX_LOGGED_OCR_CANDIDATE_URLS
        ]:
            coreLogger.info("ocr_candidate_image_url={}", imageUrl)

        for warning in resultData["warnings"]:
            coreLogger.warning("warning={}", warning)

    def _Logger(self, functionName: str) -> Any:
        return logger.bind(
            className=self.__class__.__name__,
            functionName=functionName,
        )

    def _FormatFieldValue(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if len(value) <= DEFAULT_MAX_LOGGED_FIELD_VALUE_CHARACTERS:
            return value
        return "{0}...".format(
            value[:DEFAULT_MAX_LOGGED_FIELD_VALUE_CHARACTERS],
        )


if __name__ == "__main__":
    KurlyMarketParseSmokeRunner().Run()
