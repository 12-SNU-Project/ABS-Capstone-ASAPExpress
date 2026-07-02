"""KurlyMarket 상품 페이지 parser/OCR fallback runtime smoke."""

import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List
from urllib.parse import urlsplit, urlunsplit

PROJECT_ROOT_PATH = Path(__file__).resolve().parent
SOURCE_ROOT_PATH = PROJECT_ROOT_PATH / "src"
if str(SOURCE_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT_PATH))

from bussiness_logic.app_config import LoadAppConfig  # noqa: E402
from bussiness_logic.artifact_paths import ExtractProductIdFromUrl  # noqa: E402
from bussiness_logic.bridge.factory import (  # noqa: E402
    BuildRuntimeAdapter,
    RuntimeAdapterBuildError,
)
from bussiness_logic.bridge.selector import BuildLlmRuntimeConfigFromEnv  # noqa: E402
from bussiness_logic.input_process.reconstruction import (  # noqa: E402
    ProductInputReconstructionService,
)
from bussiness_logic.product.ocr.paddle_ocr import (  # noqa: E402
    PaddleOcrEngine,
    PaddleOcrVlEngine,
)
from bussiness_logic.product.ocr.ocr_fallback import (  # noqa: E402
    ProductOcrImageDownloader,
    ProductOcrImageResult,
)
from bussiness_logic.product.pipeline.pipeline import KurlyProductPipeline  # noqa: E402
from bussiness_logic.product.pipeline.pipeline_schema import KurlyPipelineInput  # noqa: E402
from bussiness_logic.product.web_parser.kurly_domestic import (  # noqa: E402
    KurlyDomesticPageParser,
)
from bussiness_logic.product.web_parser.kurly_global import KurlyGlobalPageParser  # noqa: E402
from bussiness_logic.product.web_parser.kurly_market_collector import (  # noqa: E402
    KurlyPageCollector,
)
from bussiness_logic.product.web_parser.kurly_page_adapter import (  # noqa: E402
    KurlyPageAdapter,
)
from backend.pipeline_projection import InputProcessingViewProjector  # noqa: E402


VLM_SOURCE_TYPES = {"vlm_table", "pp_table"}
NUTRITION_MARKERS = (
    "영양",
    "열량",
    "나트",
    "탄수",
    "당류",
    "지방",
    "트랜스",
    "포화",
    "콜레스",
    "단백",
    "kcal",
    "mg",
)
INGREDIENT_MARKERS = ("원재료", "원료", "원제", "함량", "함유", "ingredients")
LOGGER = logging.getLogger("kurly_market_smoke")
ANSWER_URL_COLUMNS = (
    "링크",
    "상품 상세",
    "url",
    "URL",
    "product_url",
    "product_page_url",
)
ANSWER_TARIC10_COLUMNS = (
    "EU HS CODE",
    "실제 taric10 코드",
    "실제 TARIC10 코드",
    "actual_taric10",
    "taric10",
    "TARIC10",
    "미국 HS Code",
)
RECALL_LEVELS = (("hs2", 2), ("hs4", 4), ("hs6", 6), ("cn8", 8))


@dataclass(frozen=True, slots=True)
class AnswerRecord:
    url: str
    productId: str
    taric10: str


class _BoundLogger:
    def __init__(self, logger: logging.Logger, className: str, functionName: str) -> None:
        self._logger = logger
        self._prefix = f"{className}::{functionName}: "

    def info(self, message: str, *args: Any) -> None:
        self._log(logging.INFO, message, *args)

    def warning(self, message: str, *args: Any) -> None:
        self._log(logging.WARNING, message, *args)

    def error(self, message: str, *args: Any) -> None:
        self._log(logging.ERROR, message, *args)

    def _log(self, level: int, message: str, *args: Any) -> None:
        try:
            renderedMessage = message.format(*args)
        except Exception:
            renderedMessage = " ".join([message, *[str(arg) for arg in args]])
        self._logger.log(level, "%s%s", self._prefix, renderedMessage)


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
    parser.add_argument(
        "--check-ui-binding",
        action="store_true",
        help="현재 Dash Reconstruction Drawer 바인딩 가능 여부를 함께 검사합니다.",
    )
    parser.add_argument(
        "--classify-reconstruction",
        action="store_true",
        help=(
            "LLM reconstruction 결과를 입력으로 ProductUnderstanding, "
            "DomainRouter, Classification 후보와 계층 recall을 함께 검사합니다."
        ),
    )
    parser.add_argument(
        "--stage1-review-mode",
        choices=("compact", "full"),
        default="compact",
        help=(
            "Classification LLM 검증 모드입니다. 기본 compact, "
            "full은 후보별 evidence/EBTI 검토 JSON을 직접 요청합니다."
        ),
    )
    parsedArguments = parser.parse_args(arguments)
    if parsedArguments.compare_max_images < 0:
        parser.error("--compare-max-images must be greater than or equal to 0")
    return parsedArguments


def _ShortText(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _CompactText(value: Any) -> str:
    return str(value or "").replace(" ", "").lower()


def _ContainsMarker(value: Any, markers: Sequence[str]) -> bool:
    text = _CompactText(value)
    return any(marker.replace(" ", "").lower() in text for marker in markers)


def _EvidenceId(row: Mapping[str, Any]) -> str:
    return str(row.get("evidence_id") or row.get("id") or "").strip()


def _SourceRefsForTable(table: Mapping[str, Any]) -> list[str]:
    refs = [
        str(ref).strip()
        for ref in table.get("source_refs") or []
        if str(ref).strip()
    ]
    for row in table.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        refs.extend(
            str(ref).strip()
            for ref in row.get("source_refs") or []
            if str(ref).strip()
        )
    return list(dict.fromkeys(refs))


def _RowText(table: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    return " ".join(
        str(value or "")
        for value in (
            table.get("table_name"),
            row.get("field_name"),
            row.get("raw_value"),
            row.get("normalized_value"),
            row.get("unit"),
            row.get("daily_value_percent"),
        )
    )


def _ProductContextForTable(
    table: Mapping[str, Any],
    evidenceRows: list[Any],
) -> str:
    evidenceById = {
        evidenceId: row
        for row in evidenceRows
        if isinstance(row, Mapping) and (evidenceId := _EvidenceId(row))
    }
    optionLabels = {
        str(row.get("option_key") or "").strip(): _ShortText(
            row.get("text") or row.get("source_label") or row.get("option_key"),
            limit=120,
        )
        for row in evidenceRows
        if (
            isinstance(row, Mapping)
            and str(row.get("source_type") or "") == "notice_option"
            and str(row.get("option_key") or "").strip()
        )
    }
    optionKeys = []
    for sourceRef in _SourceRefsForTable(table):
        row = evidenceById.get(sourceRef)
        if row is None:
            continue
        optionKey = str(row.get("option_key") or "").strip()
        if optionKey:
            optionKeys.append(optionKey)
    return ", ".join(
        optionLabels.get(optionKey, optionKey)
        for optionKey in dict.fromkeys(optionKeys)
    )


def _CompactReconstructedTables(
    tables: list[Any],
    evidenceRows: list[Any],
) -> list[dict[str, Any]]:
    compactTables: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, Mapping):
            continue
        rows = []
        for row in table.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            rows.append({
                "field_name": str(row.get("field_name") or ""),
                "raw_value": _ShortText(row.get("raw_value")),
                "normalized_value": _ShortText(
                    row.get("normalized_value") or row.get("raw_value"),
                ),
                "unit": str(row.get("unit") or ""),
                "daily_value_percent": str(row.get("daily_value_percent") or ""),
                "source_refs": [
                    str(ref)
                    for ref in (row.get("source_refs") or [])
                    if str(ref).strip()
                ],
                "validation_status": str(row.get("validation_status") or ""),
            })
        compactTables.append({
            "table_name": str(table.get("table_name") or ""),
            "product_context": _ProductContextForTable(table, evidenceRows),
            "source_refs": [
                str(ref)
                for ref in (table.get("source_refs") or [])
                if str(ref).strip()
            ],
            "rows": rows,
        })
    return compactTables


def _CompactFacts(facts: list[Any]) -> list[dict[str, Any]]:
    compactFacts: list[dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, Mapping):
            continue
        compactFacts.append({
            "field_name": str(fact.get("field_name") or ""),
            "raw_value": _ShortText(fact.get("raw_value")),
            "normalized_value": _ShortText(
                fact.get("normalized_value") or fact.get("raw_value"),
            ),
            "source_refs": [
                str(ref)
                for ref in (fact.get("source_refs") or [])
                if str(ref).strip()
            ],
            "validation_status": str(fact.get("validation_status") or ""),
            "correction_type": str(fact.get("correction_type") or ""),
        })
    return compactFacts


def _IngredientFacts(facts: list[Any]) -> list[dict[str, Any]]:
    return [
        dict(fact)
        for fact in facts
        if (
            isinstance(fact, Mapping)
            and _ContainsMarker(fact.get("field_name"), INGREDIENT_MARKERS)
        )
    ]


def _BuildCurrentReconstructionDrawerBinding(
    inputProcessingView: Mapping[str, Any],
) -> dict[str, Any]:
    reconstructedTables = inputProcessingView.get("reconstructed_detail_tables") or []
    evidenceRows = inputProcessingView.get("detail_evidence_rows") or []
    productFacts = inputProcessingView.get("classification_input_facts") or []
    factTexts = inputProcessingView.get("classification_input_text_lines") or []
    unresolvedFacts = inputProcessingView.get("unresolved_input_facts") or []
    conflicts = inputProcessingView.get("input_fact_conflicts") or []
    return {
        "render_mode": "reconstructed_tables",
        "status_table": inputProcessingView.get("reconstruction_status") or {},
        "reconstructed_tables": _CompactReconstructedTables(
            reconstructedTables if isinstance(reconstructedTables, list) else [],
            evidenceRows if isinstance(evidenceRows, list) else [],
        ),
        "classification_input_facts": _CompactFacts(
            productFacts if isinstance(productFacts, list) else [],
        ),
        "classification_input_text_lines": [
            _ShortText(text) for text in factTexts
        ] if isinstance(factTexts, list) else [],
        "unresolved_input_facts": _CompactFacts(
            unresolvedFacts if isinstance(unresolvedFacts, list) else [],
        ),
        "input_fact_conflicts": [
            _ShortText(conflict) for conflict in conflicts
        ] if isinstance(conflicts, list) else [],
    }


def _BuildPipelineChecks(
    facts: Mapping[str, Any],
    inputProcessingView: Mapping[str, Any],
) -> dict[str, Any]:
    urlIntake = facts.get("url_intake") or {}
    if not isinstance(urlIntake, Mapping):
        urlIntake = {}
    ocrSummary = urlIntake.get("ocr") or {}
    if not isinstance(ocrSummary, Mapping):
        ocrSummary = {}
    status = inputProcessingView.get("reconstruction_status") or {}
    if not isinstance(status, Mapping):
        status = {}
    evidenceRows = inputProcessingView.get("detail_evidence_rows") or []
    if not isinstance(evidenceRows, list):
        evidenceRows = []
    sourceTypes = [
        str(record.get("source_type") or "")
        for record in evidenceRows
        if isinstance(record, Mapping)
    ]
    binding = _BuildCurrentReconstructionDrawerBinding(inputProcessingView)
    hasBoundFacts = bool(
        binding.get("classification_input_facts")
        or binding.get("unresolved_input_facts")
    )
    return {
        "url_collection": bool(urlIntake),
        "ocr_image_count": (
            ocrSummary.get("image_result_count")
            or urlIntake.get("ocr_image_count")
            or 0
        ),
        "structured_table_count": ocrSummary.get("structured_table_count") or 0,
        "has_raw_ocr_evidence": "raw_ocr_tile" in sourceTypes,
        "has_vlm_evidence": any(sourceType in VLM_SOURCE_TYPES for sourceType in sourceTypes),
        "used_llm_reconstruction": bool(status.get("used_llm_reconstruction")),
        "ui_binding_ready": bool(binding.get("reconstructed_tables") or hasBoundFacts),
    }


def _BuildUiBindingDiagnostics(
    inputProcessingView: Mapping[str, Any],
) -> dict[str, Any]:
    reconstructedTables = inputProcessingView.get("reconstructed_detail_tables") or []
    evidenceRows = inputProcessingView.get("detail_evidence_rows") or []
    productFacts = inputProcessingView.get("classification_input_facts") or []
    unresolvedFacts = inputProcessingView.get("unresolved_input_facts") or []
    if not isinstance(reconstructedTables, list):
        reconstructedTables = []
    if not isinstance(evidenceRows, list):
        evidenceRows = []
    if not isinstance(productFacts, list):
        productFacts = []
    if not isinstance(unresolvedFacts, list):
        unresolvedFacts = []

    sourceTypeCounts = Counter(
        str(record.get("source_type") or "")
        for record in evidenceRows
        if isinstance(record, Mapping)
    )
    blankNormalizedRows = []
    blankRawRows = []
    skeletonRows = []
    nutritionTables = []
    ingredientTables = []
    perTableSummary = []
    tableCount = 0
    rowCount = 0
    nutritionRowCount = 0
    ingredientRowCount = 0
    ingredientFacts = _IngredientFacts([*productFacts, *unresolvedFacts])

    for table in reconstructedTables:
        if not isinstance(table, Mapping):
            continue
        tableCount += 1
        tableRows = [
            row for row in table.get("rows") or [] if isinstance(row, Mapping)
        ]
        rowCount += len(tableRows)
        tableNutritionRows = []
        tableIngredientRows = []
        for row in tableRows:
            rowSummary = {
                "table_name": table.get("table_name") or "",
                "field_name": row.get("field_name") or "",
                "raw_value": _ShortText(row.get("raw_value"), limit=220),
                "normalized_value": _ShortText(row.get("normalized_value"), limit=220),
                "validation_status": row.get("validation_status") or "",
            }
            if not str(row.get("raw_value") or "").strip():
                blankRawRows.append(rowSummary)
            if not str(row.get("normalized_value") or "").strip():
                blankNormalizedRows.append(rowSummary)
            if row.get("validation_status") == "vlm_skeleton":
                skeletonRows.append(rowSummary)
            text = _RowText(table, row)
            if _ContainsMarker(text, NUTRITION_MARKERS):
                tableNutritionRows.append(rowSummary)
            if _ContainsMarker(text, INGREDIENT_MARKERS):
                tableIngredientRows.append(rowSummary)
        if tableNutritionRows:
            nutritionRowCount += len(tableNutritionRows)
            nutritionTables.append({
                "table_name": table.get("table_name") or "",
                "row_count": len(tableNutritionRows),
                "sample_rows": tableNutritionRows[:5],
            })
        if tableIngredientRows:
            ingredientRowCount += len(tableIngredientRows)
            ingredientTables.append({
                "table_name": table.get("table_name") or "",
                "row_count": len(tableIngredientRows),
                "sample_rows": tableIngredientRows[:3],
            })
        perTableSummary.append({
            "table_name": table.get("table_name") or "",
            "row_count": len(tableRows),
            "nutrition_row_count": len(tableNutritionRows),
            "ingredient_row_count": len(tableIngredientRows),
        })

    issues = []
    if tableCount == 0:
        issues.append("no_reconstructed_tables")
    if nutritionRowCount == 0:
        issues.append("no_nutrition_rows_in_reconstructed_tables")
    if ingredientRowCount == 0 and not ingredientFacts:
        issues.append("no_ingredient_binding_rows")
    if blankNormalizedRows:
        issues.append("blank_normalized_rows")
    if skeletonRows:
        issues.append("vlm_skeleton_rows_present")

    return {
        "source_type_counts": dict(sourceTypeCounts),
        "reconstructed_table_count": tableCount,
        "reconstructed_row_count": rowCount,
        "nutrition_table_count": len(nutritionTables),
        "nutrition_row_count": nutritionRowCount,
        "ingredient_table_count": len(ingredientTables),
        "ingredient_row_count": ingredientRowCount,
        "ingredient_fact_count": len(ingredientFacts),
        "per_table_summary": perTableSummary,
        "nutrition_tables": nutritionTables,
        "ingredient_tables": ingredientTables,
        "ingredient_facts": _CompactFacts(ingredientFacts)[:8],
        "blank_raw_rows": blankRawRows,
        "blank_normalized_rows": blankNormalizedRows,
        "vlm_skeleton_rows": skeletonRows,
        "issues": issues,
    }


def BuildUiBindingSmoke(
    facts: Mapping[str, Any],
    *,
    sourceLabel: str,
) -> dict[str, Any]:
    inputProcessingView = InputProcessingViewProjector().BuildInputProcessingViewFromFacts(
        facts,
    )
    return {
        "source": sourceLabel,
        "product_id": facts.get("product_id") or "",
        "input_processing_view_keys": list(inputProcessingView.keys()),
        "reconstruction_status": inputProcessingView.get("reconstruction_status") or {},
        "pipeline_checks": _BuildPipelineChecks(facts, inputProcessingView),
        "current_ui_reconstruction_drawer_binding": (
            _BuildCurrentReconstructionDrawerBinding(inputProcessingView)
        ),
        "diagnostics": _BuildUiBindingDiagnostics(inputProcessingView),
    }


class KurlyMarketSmokeRunner:
    """실제 KurlyMarket URL에서 parser와 선택적 OCR fallback을 확인한다."""

    def __init__(
        self,
        *,
        showBrowser: bool = False,
        compareOcr: bool = False,
        compareMaxImages: int = 1,
        checkUiBinding: bool = False,
        classifyReconstruction: bool = False,
        stage1ReviewMode: str = "compact",
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
        self._checkUiBinding = checkUiBinding
        self._classifyReconstruction = classifyReconstruction
        self._stage1ReviewMode = stage1ReviewMode
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
        self._answerCsvPath = pathConfig.ResolvePath(
            PROJECT_ROOT_PATH,
            appConfig.ontology_smoke.answer_csv_path,
        )
        self._answerByUrl, self._answerByProductId = self._LoadAnswerRecords(
            self._answerCsvPath,
        )
        self._maxLoggedNoticeOptions = smokeConfig.max_logged_notice_options
        self._maxLoggedFieldsPerOption = smokeConfig.max_logged_fields_per_option
        self._maxLoggedOcrCandidateUrls = smokeConfig.max_logged_ocr_candidate_urls
        self._fieldValuePreviewCharacters = smokeConfig.field_value_preview_characters
        self._ocrTextPreviewCharacters = smokeConfig.ocr_text_preview_characters
        self._pipelineOcrEngine: Any = None
        self._pipelineRawOcrEngine: Any = None

    @staticmethod
    def _LoadAnswerRecords(
        answerCsvPath: Path,
    ) -> tuple[dict[str, AnswerRecord], dict[str, AnswerRecord]]:
        if not answerCsvPath.exists():
            return {}, {}
        byUrl: dict[str, AnswerRecord] = {}
        byProductId: dict[str, AnswerRecord] = {}
        with answerCsvPath.open(newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                url = KurlyMarketSmokeRunner._FirstCsvValue(row, ANSWER_URL_COLUMNS)
                taric10 = KurlyMarketSmokeRunner._NormalizeTaric10(
                    KurlyMarketSmokeRunner._FirstCsvValue(
                        row,
                        ANSWER_TARIC10_COLUMNS,
                    )
                )
                if not url or not taric10:
                    continue
                productId = ExtractProductIdFromUrl(url)
                record = AnswerRecord(url=url, productId=productId, taric10=taric10)
                normalizedUrl = KurlyMarketSmokeRunner._NormalizeAnswerUrl(url)
                if normalizedUrl:
                    byUrl[normalizedUrl] = record
                if productId:
                    byProductId[productId] = record
        return byUrl, byProductId

    @staticmethod
    def _FirstCsvValue(row: Mapping[str, str], columns: Sequence[str]) -> str:
        for column in columns:
            value = str(row.get(column) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _NormalizeTaric10(value: object) -> str:
        digits = re.sub(r"\D", "", str(value or ""))
        if 7 <= len(digits) <= 9:
            digits = digits.zfill(10)
        return digits[:10] if len(digits) >= 10 else ""

    @staticmethod
    def _NormalizeAnswerUrl(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        parts = urlsplit(text)
        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/"),
                "",
                "",
            )
        )

    def _FindAnswerRecord(self, productUrl: str, productId: str) -> AnswerRecord | None:
        return (
            self._answerByUrl.get(self._NormalizeAnswerUrl(productUrl))
            or self._answerByProductId.get(productId)
        )

    def Run(self) -> None:
        self._ConfigureLogger()
        runLogger = self._Logger("Run")
        runLogger.info(
            (
                "KurlyMarket 상품 수집 smoke를 시작합니다 url_count={} "
                "run_ocr_fallback={} browser_mode={} compare_ocr={} "
                "classify_reconstruction={} stage1_review_mode={}"
            ),
            len(self._productUrls),
            self._runOcrFallback,
            "headless" if self._headless else "headed",
            self._compareOcr,
            self._classifyReconstruction,
            self._stage1ReviewMode,
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
            uiFacts = (
                self._BuildDashFactsFromPipelineResult(productUrl, pipelineResult)
                if (self._checkUiBinding or self._classifyReconstruction)
                else {}
            )
            if self._checkUiBinding:
                resultData["ui_binding_smoke"] = BuildUiBindingSmoke(
                    uiFacts,
                    sourceLabel=productUrl,
                )
            if self._classifyReconstruction:
                resultData["classification_smoke"] = self._RunClassificationSmoke(
                    productUrl,
                    uiFacts,
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

    def _BuildDashFactsFromPipelineResult(
        self,
        productUrl: str,
        pipelineResult: Any,
    ) -> Dict[str, Any]:
        from agents.document_pipeline import build_kurly_url_facts_from_pipeline_result

        return build_kurly_url_facts_from_pipeline_result(
            productUrl,
            pipelineResult,
            artifact_root=self._artifactRootPath,
        )

    def _RunClassificationSmoke(
        self,
        productUrl: str,
        uiFacts: Mapping[str, Any],
    ) -> Dict[str, Any]:
        from agents.blackboard import BlackboardStore
        from agents.classification_agent import ClassificationAgent
        from agents.document_pipeline import build_raw_input_from_ui
        from agents.domain_router_agent import DomainRouterAgent
        from agents.evidence_intake_agent import EvidenceIntakeAgent
        from agents.product_understanding_agent import ProductUnderstandingAgent

        rawInput = build_raw_input_from_ui(
            query=str(uiFacts.get("product_name") or productUrl),
            facts=dict(uiFacts),
        )
        productId = str(uiFacts.get("product_id") or ExtractProductIdFromUrl(productUrl))
        runDirectory = (
            self._artifactRootPath
            / productId
            / "classification-smoke"
            / datetime.now().strftime("%Y%m%dT%H%M%S%f")
        )
        store = BlackboardStore.create(
            runtime_mode="smoke",
            run_id="run_001",
            run_dir=runDirectory,
            validate_on_write=False,
        )
        agentResults = []
        previousReviewMode = os.environ.get("ASAP_STAGE1_REVIEW_MODE")
        os.environ["ASAP_STAGE1_REVIEW_MODE"] = self._stage1ReviewMode
        try:
            for agent in (
                EvidenceIntakeAgent(rawInput),
                ProductUnderstandingAgent(),
                DomainRouterAgent(),
                ClassificationAgent(),
            ):
                result = agent.execute(store)
                agentResults.append({
                    "agent_name": agent.agent_name,
                    "success": result.success,
                    "error": result.error,
                    "outputs_written": result.outputs_written,
                })
                if not result.success:
                    break
        finally:
            if previousReviewMode is None:
                os.environ.pop("ASAP_STAGE1_REVIEW_MODE", None)
            else:
                os.environ["ASAP_STAGE1_REVIEW_MODE"] = previousReviewMode

        blackboard = store.load()
        productEvidenceState = blackboard.get("product_evidence_state") or {}
        observedFacts = productEvidenceState.get("observed_facts") or {}
        productUnderstanding = blackboard.get("product_understanding") or {}
        if not isinstance(productUnderstanding, Mapping):
            productUnderstanding = {}
        routingContext = blackboard.get("routing_context") or {}
        if not isinstance(routingContext, Mapping):
            routingContext = {}
        candidateCodeSet = (blackboard.get("candidate_code_sets") or [None])[-1]
        if not isinstance(candidateCodeSet, Mapping):
            candidateCodeSet = {}
        trace = candidateCodeSet.get("classification_trace") or {}
        if not isinstance(trace, Mapping):
            trace = {}
        routeTrace = trace.get("routing_context") or {}
        if not isinstance(routeTrace, Mapping):
            routeTrace = {}
        candidates = self._BuildClassificationCandidateSmokeRows(candidateCodeSet)
        zeroScoreCodes = [
            candidate["cn8"]
            for candidate in candidates
            if float(candidate.get("score") or 0) <= 0
        ]
        classificationAgentResult = self._FindAgentResult(
            agentResults,
            "Classification_Agent",
        )
        answerRecord = self._FindAnswerRecord(productUrl, productId)
        answerRecall = self._BuildAnswerRecallSmoke(answerRecord, candidates)
        llmValidationRecommendation = self._BuildLlmValidationRecommendationSmoke(
            candidates,
        )
        return {
            "source": productUrl,
            "dash_equivalence": {
                "scope": (
                    "Integrated smoke path after merge: reconstruction facts feed "
                    "ProductUnderstanding, DomainRouter, and Beam Classification."
                ),
                "path": [
                    "KurlyProductPipeline.Run",
                    "build_kurly_url_facts_from_pipeline_result",
                    "build_raw_input_from_ui",
                    "EvidenceIntakeAgent",
                    "ProductUnderstandingAgent",
                    "DomainRouterAgent",
                    "ClassificationAgent",
                ],
                "raw_input_matches_evidence_intake": (
                    self._DoesRawInputMatchObservedFacts(rawInput, observedFacts)
                ),
                "run_dir": str(runDirectory),
                "blackboard_path": str(store.bb_path),
            },
            "input": {
                "product_name": observedFacts.get("product_name") or "",
                "classification_fact_count": (
                    len(observedFacts.get("classification_input_product_facts") or [])
                    if isinstance(
                        observedFacts.get("classification_input_product_facts"),
                        list,
                    )
                    else 0
                ),
                "classification_text_line_count": (
                    len(observedFacts.get("classification_input_fact_texts") or [])
                    if isinstance(
                        observedFacts.get("classification_input_fact_texts"),
                        list,
                    )
                    else 0
                ),
                "unresolved_fact_count": (
                    len(observedFacts.get("unresolved_product_facts") or [])
                    if isinstance(observedFacts.get("unresolved_product_facts"), list)
                    else 0
                ),
                "classification_input_text_lines": list(
                    observedFacts.get("classification_input_fact_texts") or [],
                )
                if isinstance(observedFacts.get("classification_input_fact_texts"), list)
                else [],
            },
            "status": {
                "error": classificationAgentResult.get("error"),
                "agent_success": bool(classificationAgentResult.get("success")),
                "llm_model": self._FindAgentRunModel(store, "Classification_Agent"),
                "stage1_review_mode": self._stage1ReviewMode,
                "candidate_count": len(candidates),
                "zero_score_candidate_codes": zeroScoreCodes,
                "answer_found": answerRecall.get("answer_found"),
            },
            "product_understanding": self._BuildProductUnderstandingSmoke(
                productUnderstanding,
            ),
            "domain_routing": self._BuildRoutingSmoke(
                routingContext,
                routeTrace,
            ),
            "candidates": candidates,
            "candidate_code_set": {
                "candidate_set_id": candidateCodeSet.get("candidate_set_id"),
                "product_id": candidateCodeSet.get("product_id"),
            },
            "decision": {
                "decision_status": trace.get("decision_status"),
                "backtracking_recommended": trace.get("backtracking_recommended"),
                "backtracking_occurred": trace.get("backtracking_occurred"),
            },
            "traversal": {
                "traversal_status": trace.get("traversal_status"),
                "next_action": trace.get("next_action"),
                "backtracking_target_level": trace.get("backtracking_target_level"),
                "backtracking_reason": trace.get("backtracking_reason"),
            },
            "traversal_history": list(trace.get("traversal_history") or []),
            "llm_validation_recommendation": llmValidationRecommendation,
            "answer_recall": answerRecall,
            "agent_results": agentResults,
            "agent_runs": list(store.iter_agent_runs()),
        }

    @staticmethod
    def _FindAgentResult(
        agentResults: Sequence[Mapping[str, object]],
        agentName: str,
    ) -> Mapping[str, object]:
        for agentResult in agentResults:
            if agentResult.get("agent_name") == agentName:
                return agentResult
        return {
            "success": False,
            "error": f"{agentName}_not_executed",
        }

    @staticmethod
    def _BuildAnswerRecallSmoke(
        answerRecord: AnswerRecord | None,
        candidates: Sequence[Mapping[str, object]],
    ) -> Dict[str, object]:
        if answerRecord is None:
            return {
                "answer_found": False,
                "reason": "answer_record_not_found",
            }

        expectedByLevel = {
            level: answerRecord.taric10[:codeLength]
            for level, codeLength in RECALL_LEVELS
        }
        llmRecommendedCandidate = next(
            (candidate for candidate in candidates if candidate.get("llm_recommended")),
            None,
        )
        candidateCodesByLevel = {
            level: [
                code
                for candidate in candidates[:5]
                for code in (
                    KurlyMarketSmokeRunner._CandidateCodeAtLevel(
                        candidate,
                        codeLength,
                    ),
                )
                if code
            ]
            for level, codeLength in RECALL_LEVELS
        }
        levels: dict[str, dict[str, object]] = {}
        for level, codeLength in RECALL_LEVELS:
            expectedCode = expectedByLevel[level]
            top5Codes = candidateCodesByLevel[level]
            top1Code = top5Codes[0] if top5Codes else ""
            llmRecommendedCode = (
                KurlyMarketSmokeRunner._CandidateCodeAtLevel(
                    llmRecommendedCandidate,
                    codeLength,
                )
                if llmRecommendedCandidate is not None
                else ""
            )
            levels[level] = {
                "expected": expectedCode,
                "top1_code": top1Code,
                "top5_codes": top5Codes,
                "top1_match": bool(expectedCode and top1Code == expectedCode),
                "top5_match": bool(expectedCode and expectedCode in top5Codes),
                "llm_recommended_code": llmRecommendedCode,
                "llm_recommended_match": bool(
                    expectedCode and llmRecommendedCode == expectedCode,
                ),
            }

        return {
            "answer_found": True,
            "answer": {
                "url": answerRecord.url,
                "product_id": answerRecord.productId,
                "taric10": answerRecord.taric10,
            },
            "levels": levels,
        }

    @staticmethod
    def _CandidateCodeAtLevel(
        candidate: Mapping[str, object],
        codeLength: int,
    ) -> str:
        cn8 = re.sub(r"\D", "", str(candidate.get("cn8") or ""))
        if len(cn8) >= codeLength:
            return cn8[:codeLength]
        hs6 = re.sub(r"\D", "", str(candidate.get("hs6") or ""))
        if len(hs6) >= codeLength:
            return hs6[:codeLength]
        return ""

    @staticmethod
    def _BuildLlmValidationRecommendationSmoke(
        candidates: Sequence[Mapping[str, object]],
    ) -> Dict[str, object]:
        recommendedCandidate = next(
            (candidate for candidate in candidates if candidate.get("llm_recommended")),
            None,
        )
        if recommendedCandidate is None:
            return {
                "recommended": False,
                "reason": "llm_validation_recommendation_not_found",
            }
        hierarchy = recommendedCandidate.get("hierarchy") or {}
        if not isinstance(hierarchy, Mapping):
            hierarchy = {}
        classificationBasis = recommendedCandidate.get("classification_basis") or []
        if not isinstance(classificationBasis, list):
            classificationBasis = []
        evidenceRefs = recommendedCandidate.get("classification_evidence_refs") or []
        if not isinstance(evidenceRefs, list):
            evidenceRefs = []
        supportingFacts = recommendedCandidate.get("supporting_product_facts") or []
        if not isinstance(supportingFacts, list):
            supportingFacts = []
        reason = str(classificationBasis[0]).strip() if classificationBasis else ""
        return {
            "recommended": True,
            "rank": recommendedCandidate.get("rank"),
            "hs2": hierarchy.get("hs2") or "",
            "hs4": hierarchy.get("hs4") or "",
            "hs6": hierarchy.get("hs6") or recommendedCandidate.get("hs6"),
            "cn8": hierarchy.get("cn8") or recommendedCandidate.get("cn8"),
            "taric10": recommendedCandidate.get("taric10"),
            "hard_condition_status": recommendedCandidate.get(
                "hard_condition_status",
            ),
            "reason": reason,
            "classification_evidence_refs": evidenceRefs,
            "supporting_product_facts": supportingFacts,
        }

    @staticmethod
    def _BuildProductUnderstandingSmoke(
        productUnderstanding: Mapping[str, object],
    ) -> Dict[str, object]:
        identity = productUnderstanding.get("identity_lane") or {}
        if not isinstance(identity, Mapping):
            identity = {}
        coiEvidence = productUnderstanding.get("coi_evidence") or {}
        if not isinstance(coiEvidence, Mapping):
            coiEvidence = {}
        encyclopediaEvidence = productUnderstanding.get("encyclopedia_evidence") or {}
        if not isinstance(encyclopediaEvidence, Mapping):
            encyclopediaEvidence = {}
        routingTerms = productUnderstanding.get("routing_terms") or []
        if not isinstance(routingTerms, list):
            routingTerms = []
        return {
            "understanding_id": productUnderstanding.get("understanding_id"),
            "product_id": productUnderstanding.get("product_id"),
            "product_name": productUnderstanding.get("product_name"),
            "fact_count": len(
                productUnderstanding.get("classification_input_product_facts")
                or [],
            ),
            "fact_text_count": len(
                productUnderstanding.get("classification_input_fact_texts")
                or [],
            ),
            "identity": {
                "commercial_identity": identity.get("commercial_identity"),
                "ingredient_class": identity.get("ingredient_class"),
                "food_form": identity.get("food_form"),
                "processing_state": identity.get("processing_state"),
                "translated_product_name": identity.get("translated_product_name"),
                "normalized_tariff_description": identity.get(
                    "normalized_tariff_description",
                ),
                "product_form_terms": identity.get("product_form_terms") or [],
                "domain_hints": identity.get("domain_hints") or [],
                "chapter_hint_terms": identity.get("chapter_hint_terms") or [],
                "chapter_hint_source_terms": identity.get(
                    "chapter_hint_source_terms",
                )
                or [],
                "chapter_hint_basis": identity.get("chapter_hint_basis"),
                "chapter_hint_status": identity.get("chapter_hint_status"),
                "understanding_mode": identity.get("understanding_mode"),
                "needs_review": identity.get("needs_review"),
                "confidence": identity.get("confidence"),
            },
            "coi": {
                "matched_documents": coiEvidence.get("matched_documents") or [],
                "error": coiEvidence.get("error") or "",
            },
            "encyclopedia": {
                "configured": encyclopediaEvidence.get("configured"),
                "quality_status": encyclopediaEvidence.get("quality_status"),
                "entry_count": len(encyclopediaEvidence.get("entries") or []),
                "error": encyclopediaEvidence.get("error") or "",
            },
            "routing_terms_preview": routingTerms[:12],
            "unknowns": productUnderstanding.get("unknowns") or [],
        }

    @staticmethod
    def _BuildRoutingSmoke(
        routingContext: Mapping[str, object],
        routeTrace: Mapping[str, object],
    ) -> Dict[str, object]:
        return {
            "routing_context_id": routingContext.get("routing_context_id"),
            "candidate_hs2": routingContext.get("candidate_hs2") or [],
            "blocked_hs2": routingContext.get("blocked_hs2") or [],
            "strict_route": routingContext.get("strict_route"),
            "fallback_allowed": routingContext.get("fallback_allowed"),
            "domain_scopes": routingContext.get("domain_scopes") or [],
            "pre_gate_domains": routingContext.get("pre_gate_domains") or [],
            "routing_basis": routingContext.get("routing_basis") or {},
            "missing_facts": routingContext.get("missing_facts") or [],
            "classification_boundary": {
                "boundary_applied": routeTrace.get("boundary_applied"),
                "fallback_used": routeTrace.get("fallback_used"),
            },
        }

    @staticmethod
    def _BuildClassificationCandidateSmokeRows(
        candidateCodeSet: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        candidates = candidateCodeSet.get("candidates") or []
        if not isinstance(candidates, list):
            return out
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            staticTree = candidate.get("candidate_static_tree") or {}
            if not isinstance(staticTree, Mapping):
                staticTree = {}
            hierarchy = KurlyMarketSmokeRunner._BuildCandidateHierarchySmoke(
                candidate,
            )
            out.append({
                "rank": candidate.get("rank"),
                "cn8": hierarchy.get("cn8") or candidate.get("cn8"),
                "hs6": hierarchy.get("hs6") or candidate.get("hs6"),
                "hierarchy": hierarchy,
                "taric10": candidate.get("taric10"),
                "score": staticTree.get("total_score"),
                "llm_recommended": candidate.get("llm_recommended"),
                "hard_condition_status": candidate.get("hard_condition_status"),
                "taric10_branch_count": candidate.get("taric10_branch_count"),
                "retrieval_sources": staticTree.get("retrieval_sources") or [],
                "matched_keywords": staticTree.get("matched_keywords") or [],
                "score_breakdown": staticTree.get("score_breakdown") or {},
                "classification_basis": candidate.get("classification_basis") or [],
                "supporting_product_facts": (
                    candidate.get("supporting_product_facts") or []
                ),
                "classification_evidence_refs": (
                    candidate.get("classification_evidence_refs") or []
                ),
                "similar_ebti_cases": candidate.get("similar_ebti_cases") or [],
            })
        return out

    @staticmethod
    def _BuildCandidateHierarchySmoke(
        candidate: Mapping[str, object],
    ) -> Dict[str, str]:
        cn8 = re.sub(r"\D", "", str(candidate.get("cn8") or ""))
        hs6 = re.sub(r"\D", "", str(candidate.get("hs6") or ""))
        sourceCode = cn8 or hs6
        return {
            levelName: sourceCode[:codeLength]
            for levelName, codeLength in RECALL_LEVELS
            if len(sourceCode) >= codeLength
        }

    @staticmethod
    def _DoesRawInputMatchObservedFacts(
        rawInput: Mapping[str, Any],
        observedFacts: Mapping[str, Any],
    ) -> bool:
        keys = (
            "product_name",
            "description",
            "classification_input_product_facts",
            "classification_input_fact_texts",
            "unresolved_product_facts",
            "product_fact_conflicts",
            "ocr_text",
            "source_urls",
            "origin_country",
            "intended_use",
            "warnings",
            "input_reconstruction",
        )
        return all(rawInput.get(key) == observedFacts.get(key) for key in keys)

    @staticmethod
    def _FindAgentRunModel(store: Any, agentName: str) -> str | None:
        for agentRun in store.iter_agent_runs():
            if agentRun.get("agent_name") == agentName:
                return agentRun.get("llm_model")
        return None

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
        self._LogClassificationSmoke(resultData)

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
        uiBinding = resultData.get("ui_binding_smoke")
        if isinstance(uiBinding, dict):
            diagnostics = uiBinding.get("diagnostics") or {}
            eventLogger.info(
                "ui_binding_ready={} tables={} ingredient_rows={} nutrition_rows={} issues={}",
                (uiBinding.get("pipeline_checks") or {}).get("ui_binding_ready"),
                diagnostics.get("reconstructed_table_count", 0),
                diagnostics.get("ingredient_row_count", 0),
                diagnostics.get("nutrition_row_count", 0),
                diagnostics.get("issues", []),
            )

    def _LogClassificationSmoke(self, resultData: Dict[str, Any]) -> None:
        classificationData = resultData.get("classification_smoke")
        if not isinstance(classificationData, dict):
            return
        classificationLogger = self._Logger("_LogClassificationSmoke")
        status = classificationData.get("status") or {}
        productUnderstanding = classificationData.get("product_understanding") or {}
        domainRouting = classificationData.get("domain_routing") or {}
        decision = classificationData.get("decision") or {}
        traversal = classificationData.get("traversal") or {}
        llmValidationRecommendation = (
            classificationData.get("llm_validation_recommendation") or {}
        )
        answerRecall = classificationData.get("answer_recall") or {}
        classificationLogger.info("===== INTEGRATED PIPELINE MERGE CHECK =====")
        for agentResult in classificationData.get("agent_results") or []:
            classificationLogger.info(
                "agent name={} success={} error={} outputs={}",
                agentResult.get("agent_name"),
                agentResult.get("success"),
                agentResult.get("error"),
                agentResult.get("outputs_written"),
            )
        classificationLogger.info(
            (
                "product_understanding id={} product={} facts={} fact_texts={} "
                "identity={}/{}/{} coi_docs={} encyclopedia={}"
            ),
            productUnderstanding.get("understanding_id"),
            productUnderstanding.get("product_name"),
            productUnderstanding.get("fact_count"),
            productUnderstanding.get("fact_text_count"),
            (productUnderstanding.get("identity") or {}).get("ingredient_class"),
            (productUnderstanding.get("identity") or {}).get("food_form"),
            (productUnderstanding.get("identity") or {}).get("processing_state"),
            len((productUnderstanding.get("coi") or {}).get("matched_documents") or []),
            (productUnderstanding.get("encyclopedia") or {}).get("quality_status"),
        )
        classificationLogger.info(
            (
                "domain_router routing_context_id={} candidate_hs2={} "
                "blocked_hs2={} strict_route={} fallback_allowed={} "
                "boundary_applied={} fallback_used={} missing_facts={}"
            ),
            domainRouting.get("routing_context_id"),
            domainRouting.get("candidate_hs2"),
            domainRouting.get("blocked_hs2"),
            domainRouting.get("strict_route"),
            domainRouting.get("fallback_allowed"),
            (domainRouting.get("classification_boundary") or {}).get(
                "boundary_applied",
            ),
            (domainRouting.get("classification_boundary") or {}).get("fallback_used"),
            domainRouting.get("missing_facts"),
        )
        classificationLogger.info(
            (
                "classification_smoke error={} candidates={} zero_score={} "
                "decision={} backtracking={} traversal={} raw_input_match={} "
                "answer_found={}"
            ),
            status.get("error"),
            status.get("candidate_count"),
            status.get("zero_score_candidate_codes"),
            decision.get("decision_status"),
            decision.get("backtracking_recommended"),
            traversal.get("traversal_status"),
            (classificationData.get("dash_equivalence") or {}).get(
                "raw_input_matches_evidence_intake",
            ),
            answerRecall.get("answer_found"),
        )
        classificationLogger.info(
            (
                "llm_validation_recommendation recommended={} rank={} cn8={} "
                "hs6={} taric10={} hard_condition={} reason={}"
            ),
            llmValidationRecommendation.get("recommended"),
            llmValidationRecommendation.get("rank"),
            llmValidationRecommendation.get("cn8"),
            llmValidationRecommendation.get("hs6"),
            llmValidationRecommendation.get("taric10"),
            llmValidationRecommendation.get("hard_condition_status"),
            llmValidationRecommendation.get("reason"),
        )
        self._LogAnswerRecall(classificationLogger, answerRecall)
        for candidate in classificationData.get("candidates") or []:
            classificationLogger.info(
                (
                    "classification_candidate rank={} cn8={} hs6={} "
                    "score={} llm_recommended={} taric_branches={} "
                    "evidence_refs={} ebti_cases={}"
                ),
                candidate.get("rank"),
                candidate.get("cn8"),
                candidate.get("hs6"),
                candidate.get("score"),
                candidate.get("llm_recommended"),
                candidate.get("taric10_branch_count"),
                len(candidate.get("classification_evidence_refs") or []),
                len(candidate.get("similar_ebti_cases") or []),
            )
        classificationLogger.info("===== END INTEGRATED PIPELINE MERGE CHECK =====")

    def _LogAnswerRecall(
        self,
        logger: _BoundLogger,
        answerRecall: Mapping[str, object],
    ) -> None:
        if not answerRecall.get("answer_found"):
            logger.info("answer_recall skipped reason={}", answerRecall.get("reason"))
            return
        answer = answerRecall.get("answer") or {}
        if not isinstance(answer, Mapping):
            answer = {}
        logger.info(
            "answer_recall expected_taric10={} answer_product_id={}",
            answer.get("taric10"),
            answer.get("product_id"),
        )
        levels = answerRecall.get("levels") or {}
        if not isinstance(levels, Mapping):
            return
        for levelName, levelData in levels.items():
            if not isinstance(levelData, Mapping):
                continue
            logger.info(
                (
                    "answer_recall level={} expected={} top1={} top1_match={} "
                    "top5_match={} llm_recommended={} "
                    "llm_recommended_match={} top5_codes={}"
                ),
                levelName,
                levelData.get("expected"),
                levelData.get("top1_code"),
                levelData.get("top1_match"),
                levelData.get("top5_match"),
                levelData.get("llm_recommended_code"),
                levelData.get("llm_recommended_match"),
                levelData.get("top5_codes"),
            )

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
        recallSummary = self._BuildAnswerRecallSummary(results)
        if recallSummary["evaluated_count"]:
            for levelName, levelSummary in recallSummary["levels"].items():
                summaryLogger.info(
                    (
                        "classification_recall level={} evaluated={} "
                        "top1={}/{} ({}) top5={}/{} ({}) "
                        "llm_recommended={}/{} ({})"
                    ),
                    levelName,
                    levelSummary["evaluated_count"],
                    levelSummary["top1_match_count"],
                    levelSummary["evaluated_count"],
                    levelSummary["top1_recall"],
                    levelSummary["top5_match_count"],
                    levelSummary["evaluated_count"],
                    levelSummary["top5_recall"],
                    levelSummary["llm_recommended_match_count"],
                    levelSummary["evaluated_count"],
                    levelSummary["llm_recommended_recall"],
                )
        elif any("classification_smoke" in result for result in results):
            summaryLogger.info(
                "classification_recall skipped answer_source={} matched_rows=0",
                self._answerCsvPath,
            )
        if self._logFullResult:
            summaryLogger.info(
                "\n{}",
                json.dumps(results, ensure_ascii=False, indent=2),
            )

    @staticmethod
    def _BuildAnswerRecallSummary(
        results: Sequence[Mapping[str, object]],
    ) -> Dict[str, object]:
        levelTotals = {
            levelName: {
                "evaluated_count": 0,
                "top1_match_count": 0,
                "top5_match_count": 0,
                "llm_recommended_match_count": 0,
            }
            for levelName, _ in RECALL_LEVELS
        }
        for result in results:
            classificationSmoke = result.get("classification_smoke") or {}
            if not isinstance(classificationSmoke, Mapping):
                continue
            answerRecall = classificationSmoke.get("answer_recall") or {}
            if not isinstance(answerRecall, Mapping) or not answerRecall.get(
                "answer_found"
            ):
                continue
            levels = answerRecall.get("levels") or {}
            if not isinstance(levels, Mapping):
                continue
            for levelName, _ in RECALL_LEVELS:
                levelData = levels.get(levelName) or {}
                if not isinstance(levelData, Mapping):
                    continue
                levelTotals[levelName]["evaluated_count"] += 1
                if levelData.get("top1_match"):
                    levelTotals[levelName]["top1_match_count"] += 1
                if levelData.get("top5_match"):
                    levelTotals[levelName]["top5_match_count"] += 1
                if levelData.get("llm_recommended_match"):
                    levelTotals[levelName]["llm_recommended_match_count"] += 1

        levelsOut: dict[str, dict[str, object]] = {}
        evaluatedCounts: list[int] = []
        for levelName, totals in levelTotals.items():
            evaluatedCount = totals["evaluated_count"]
            evaluatedCounts.append(evaluatedCount)
            top1Count = totals["top1_match_count"]
            top5Count = totals["top5_match_count"]
            llmRecommendedCount = totals["llm_recommended_match_count"]
            levelsOut[levelName] = {
                **totals,
                "top1_recall": (
                    round(top1Count / evaluatedCount, 4)
                    if evaluatedCount
                    else 0.0
                ),
                "top5_recall": (
                    round(top5Count / evaluatedCount, 4)
                    if evaluatedCount
                    else 0.0
                ),
                "llm_recommended_recall": (
                    round(llmRecommendedCount / evaluatedCount, 4)
                    if evaluatedCount
                    else 0.0
                ),
            }
        return {
            "evaluated_count": max(evaluatedCounts) if evaluatedCounts else 0,
            "levels": levelsOut,
        }

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
        logging.basicConfig(
            level=logging.INFO,
            format="[%(levelname)s] %(message)s",
            stream=sys.stderr,
            force=True,
        )

    def _Logger(self, functionName: str) -> _BoundLogger:
        return _BoundLogger(LOGGER, self.__class__.__name__, functionName)


if __name__ == "__main__":
    cliArguments = ParseArguments()
    KurlyMarketSmokeRunner(
        showBrowser=cliArguments.headed,
        compareOcr=cliArguments.compare_ocr,
        compareMaxImages=cliArguments.compare_max_images,
        checkUiBinding=cliArguments.check_ui_binding,
        classifyReconstruction=cliArguments.classify_reconstruction,
        stage1ReviewMode=cliArguments.stage1_review_mode,
    ).Run()
