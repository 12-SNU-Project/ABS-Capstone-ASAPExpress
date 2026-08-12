"""상품 이미지 OCR adapter."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from difflib import SequenceMatcher
from html.parser import HTMLParser
from math import ceil, floor
import re
import unicodedata
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, computed_field

from bussiness_logic.product.ocr.ocr_image_tiling import (
    ProductOcrImageTile,
    ProductOcrImageTilePlanner,
)
from bussiness_logic.utils import NormalizeWhiteSpace

TABLE_GROUNDING_TEXT_COVERAGE_THRESHOLD = 0.72
TABLE_GROUNDING_TOKEN_SIMILARITY_THRESHOLD = 0.8


class ProductOcrError(RuntimeError):
    """OCR engine 초기화 또는 추론이 실패했을 때 사용한다."""


@dataclass(frozen=True)
class ProductOcrTextRegion:
    """Raw OCR 텍스트와 원본 이미지 좌표."""

    text: str
    bounds: Tuple[int, int, int, int]


class ProductTableRecognitionEvidence(BaseModel):
    """TableRecognitionV2가 반환한 비교용 표 evidence."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    sourceName: str = Field(
        default="table_recognition_v2",
        alias="source_name",
    )
    html: str = ""
    cellTexts: List[str] = Field(default_factory=list, alias="cell_texts")
    cellBounds: List[Tuple[float, float, float, float]] = Field(
        default_factory=list,
        alias="cell_bounds",
    )


class ProductTableLayoutRegion(BaseModel):
    """PP-Structure layout box와 실제 VLM crop 선택 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    label: str = ""
    score: Optional[float] = None
    reportedBounds: Optional[Tuple[float, float, float, float]] = Field(
        default=None,
        alias="reported_bounds",
    )
    cropBounds: Optional[Tuple[int, int, int, int]] = Field(
        default=None,
        alias="crop_bounds",
    )
    selectedForVlm: bool = Field(default=False, alias="selected_for_vlm")
    recognitionPayloadAvailable: bool = Field(
        default=False,
        alias="recognition_payload_available",
    )
    issues: List[str] = Field(default_factory=list)


class ProductTableLayoutDiagnostic(BaseModel):
    """타일 하나의 PP-Structure layout 관측 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    tileIndex: Optional[int] = Field(default=None, alias="tile_index")
    tileOriginX: int = Field(default=0, alias="tile_origin_x")
    tileOriginY: int = Field(default=0, alias="tile_origin_y")
    imageWidth: int = Field(alias="image_width")
    imageHeight: int = Field(alias="image_height")
    layoutPayloadAvailable: bool = Field(
        default=False,
        alias="layout_payload_available",
    )
    rawRegionCount: int = Field(default=0, alias="raw_region_count")
    regions: List[ProductTableLayoutRegion] = Field(default_factory=list)
    parseIssues: List[str] = Field(default_factory=list, alias="parse_issues")
    directRecognitionAttempted: bool = Field(
        default=False,
        alias="direct_recognition_attempted",
    )
    directRecognitionPayloadCount: int = Field(
        default=0,
        alias="direct_recognition_payload_count",
    )
    directRecognitionTables: List[ProductTableRecognitionEvidence] = Field(
        default_factory=list,
        alias="direct_recognition_tables",
    )
    directRecognitionError: Optional[str] = Field(
        default=None,
        alias="direct_recognition_error",
    )
    error: Optional[str] = None


class ProductOcrTableResult(BaseModel):
    """구조 OCR에서 추출한 단일 표 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    tableIndex: int = Field(alias="table_index")
    sourceName: str = Field(default="structured_ocr", alias="source_name")
    tableName: str = Field(default="", alias="table_name")
    pageIndex: Optional[int] = Field(default=None, alias="page_index")
    tileIndex: Optional[int] = Field(default=None, alias="tile_index")
    html: str = ""
    cellTexts: List[str] = Field(default_factory=list, alias="cell_texts")
    plainText: str = Field(default="", alias="plain_text")
    sourceRows: List[str] = Field(default_factory=list, alias="source_rows")
    validationStatus: str = Field(default="unverified", alias="validation_status")
    validationIssues: List[str] = Field(
        default_factory=list,
        alias="validation_issues",
    )
    tableRecognitionEvidence: Optional[ProductTableRecognitionEvidence] = Field(
        default=None,
        alias="table_recognition_evidence",
    )


class ProductOcrTableCandidate(BaseModel):
    """VLM 원본 후보의 감사 snapshot과 승인 전 검증 상태."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    tableIndex: int = Field(alias="table_index")
    sourceName: str = Field(default="structured_ocr", alias="source_name")
    tableName: str = Field(default="", alias="table_name")
    tileIndex: Optional[int] = Field(default=None, alias="tile_index")
    html: str = ""
    cellTexts: List[str] = Field(default_factory=list, alias="cell_texts")
    plainText: str = Field(default="", alias="plain_text")
    sourceRows: List[str] = Field(default_factory=list, alias="source_rows")
    reportedBounds: Optional[Tuple[float, float, float, float]] = Field(
        default=None,
        alias="reported_bounds",
    )
    localizationStatus: str = Field(
        default="unavailable",
        alias="localization_status",
    )
    validationStatus: str = Field(default="candidate", alias="validation_status")
    validationIssues: List[str] = Field(
        default_factory=list,
        alias="validation_issues",
    )
    tableRecognitionEvidence: Optional[ProductTableRecognitionEvidence] = Field(
        default=None,
        alias="table_recognition_evidence",
    )


class ProductOcrRegionGroundingMatch(BaseModel):
    """VLM cell과 일치한 screening OCR 영역."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    regionIndex: int = Field(alias="region_index")
    text: str
    bounds: Tuple[int, int, int, int]
    matchScore: float = Field(alias="match_score")


class ProductOcrCellGroundingDiagnostic(BaseModel):
    """VLM cell 하나의 OCR 근거 일치 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    cellIndex: int = Field(alias="cell_index")
    role: str
    text: str
    status: str
    textCoverage: float = Field(alias="text_coverage")
    textTokens: List[str] = Field(default_factory=list, alias="text_tokens")
    missingTextTokens: List[str] = Field(
        default_factory=list,
        alias="missing_text_tokens",
    )
    numericTokens: List[str] = Field(
        default_factory=list,
        alias="numeric_tokens",
    )
    missingNumericTokens: List[str] = Field(
        default_factory=list,
        alias="missing_numeric_tokens",
    )
    matchedRegions: List[ProductOcrRegionGroundingMatch] = Field(
        default_factory=list,
        alias="matched_regions",
    )
    issues: List[str] = Field(default_factory=list)


class ProductOcrTableRowGroundingDiagnostic(BaseModel):
    """VLM table row의 OCR grounding 진단."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    rowIndex: int = Field(alias="row_index")
    sourceText: str = Field(default="", alias="source_text")
    status: str
    derivedBounds: Optional[Tuple[int, int, int, int]] = Field(
        default=None,
        alias="derived_bounds",
    )
    cells: List[ProductOcrCellGroundingDiagnostic] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)


class ProductOcrTableGroundingDiagnostic(BaseModel):
    """VLM 후보 표와 screening OCR 사이의 smoke 전용 비교 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    tableIndex: int = Field(alias="table_index")
    sourceName: str = Field(default="", alias="source_name")
    tableName: str = Field(default="", alias="table_name")
    matchingPolicy: str = Field(
        default="ocr_region_row_v1",
        alias="matching_policy",
    )
    coordinateSpace: str = Field(
        default="original_image",
        alias="coordinate_space",
    )
    textCoverageThreshold: float = Field(
        default=TABLE_GROUNDING_TEXT_COVERAGE_THRESHOLD,
        alias="text_coverage_threshold",
    )
    tokenSimilarityThreshold: float = Field(
        default=TABLE_GROUNDING_TOKEN_SIMILARITY_THRESHOLD,
        alias="token_similarity_threshold",
    )
    status: str
    rowCount: int = Field(alias="row_count")
    groundedRowCount: int = Field(alias="grounded_row_count")
    rejectedRowCount: int = Field(alias="rejected_row_count")
    derivedBounds: Optional[Tuple[int, int, int, int]] = Field(
        default=None,
        alias="derived_bounds",
    )
    rows: List[ProductOcrTableRowGroundingDiagnostic] = Field(
        default_factory=list,
    )


class ProductOcrTileTextResult(BaseModel):
    """타일 단위 raw OCR 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    tileIndex: Optional[int] = Field(default=None, alias="tile_index")
    text: str = ""


class ProductStructuredOcrResult(BaseModel):
    """원본 후보와 Reconstruction에 승인된 표를 분리해 보존한다."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    text: str = ""
    structuredText: str = Field(default="", alias="structured_text")
    rawText: str = Field(default="", alias="raw_text")
    textMergeMode: str = Field(default="raw_only", alias="text_merge_mode")
    rawTileTexts: List[ProductOcrTileTextResult] = Field(
        default_factory=list,
        alias="raw_tile_texts",
    )
    usedStructuredTables: bool = Field(
        default=False,
        alias="used_structured_tables",
    )
    fallbackReason: Optional[str] = Field(default=None, alias="fallback_reason")
    tables: List[ProductOcrTableResult] = Field(default_factory=list)
    tableCandidates: List[ProductOcrTableCandidate] = Field(
        default_factory=list,
        alias="table_candidates",
    )
    layoutDiagnostics: List[ProductTableLayoutDiagnostic] = Field(
        default_factory=list,
        alias="layout_diagnostics",
    )
    tableGroundingDiagnostics: List[ProductOcrTableGroundingDiagnostic] = Field(
        default_factory=list,
        alias="table_grounding_diagnostics",
    )
    warnings: List[str] = Field(default_factory=list)

    @computed_field(alias="raw_table_ocr")
    @property
    def rawTableOcr(self) -> str:
        return self.structuredText

    @computed_field(alias="raw_ocr")
    @property
    def rawOcr(self) -> str:
        return self.rawText


class ProductOcrEngine(ABC):
    """이미지 bytes에서 OCR 텍스트를 추출하는 adapter interface."""

    @abstractmethod
    def ExtractTextFromImage(self, imageBytes: bytes) -> str:
        raise NotImplementedError

    def BuildArtifactImageTiles(
        self,
        imageBytes: bytes,
    ) -> List[Tuple[Optional[int], bytes]]:
        return [(None, imageBytes)]

    def ExtractStructuredTextFromImage(
        self,
        imageBytes: bytes,
    ) -> ProductStructuredOcrResult:
        rawText = self.ExtractTextFromImage(imageBytes)
        return ProductStructuredOcrResult(
            text=rawText,
            rawText=rawText,
            textMergeMode="raw_only",
            rawTileTexts=[ProductOcrTileTextResult(text=rawText)] if rawText else [],
            fallbackReason="structured_ocr_not_supported",
        )

    def ExtractStructuredTextWithRegionsFromImage(
        self,
        imageBytes: bytes,
    ) -> Tuple[ProductStructuredOcrResult, List[ProductOcrTextRegion]]:
        return self.ExtractStructuredTextFromImage(imageBytes), []


class PaddleOcrEngine(ProductOcrEngine):
    """PaddleOCR 기반 OCR adapter."""

    def __init__(
        self,
        lang: str = "korean",
        device: Optional[str] = None,
        useDocOrientationClassify: bool = False,
        useDocUnwarping: bool = False,
        useTextlineOrientation: bool = False,
        extraOptions: Optional[Dict[str, object]] = None,
    ) -> None:
        self._lang = lang
        self._device = device
        self._useDocOrientationClassify = useDocOrientationClassify
        self._useDocUnwarping = useDocUnwarping
        self._useTextlineOrientation = useTextlineOrientation
        self._extraOptions = dict(extraOptions or {})
        self._ocr: object = None
        self.Initialize()

    def Initialize(self) -> None:
        """PaddleOCR 모델을 생성 시점에 한 번만 초기화한다."""

        if self._ocr is not None:
            return

        self._ocr = self._CreateOcr()

    def IsInitialized(self) -> bool:
        return self._ocr is not None

    def ExtractTextFromImage(self, imageBytes: bytes) -> str:
        structuredResult, _ = self.ExtractStructuredTextWithRegionsFromImage(
            imageBytes,
        )
        return structuredResult.text

    def ExtractStructuredTextFromImage(
        self,
        imageBytes: bytes,
    ) -> ProductStructuredOcrResult:
        structuredResult, _ = self.ExtractStructuredTextWithRegionsFromImage(
            imageBytes,
        )
        return structuredResult

    def ExtractStructuredTextWithRegionsFromImage(
        self,
        imageBytes: bytes,
    ) -> Tuple[ProductStructuredOcrResult, List[ProductOcrTextRegion]]:
        image = self._DecodeImageBytes(imageBytes)
        result = self._PredictDecodedImage(image)
        rawText = "\n".join(self._ExtractResultTexts(result))
        return (
            ProductStructuredOcrResult(
                text=rawText,
                rawText=rawText,
                textMergeMode="raw_only",
                rawTileTexts=(
                    [ProductOcrTileTextResult(text=rawText)]
                    if rawText
                    else []
                ),
                fallbackReason="structured_ocr_not_supported",
            ),
            self._ExtractTextRegions(result),
        )

    def _PredictDecodedImage(self, image: object) -> object:
        ocr = self._ReadInitializedOcr()

        if hasattr(ocr, "predict"):
            return ocr.predict(image)
        elif hasattr(ocr, "ocr"):
            return ocr.ocr(image, cls=self._useTextlineOrientation)
        raise ProductOcrError("PaddleOCR object does not expose predict or ocr.")

    def _EncodeImageBytes(self, image: object, suffix: str = ".jpg") -> bytes:
        return _EncodeImageBytes(image, suffix)

    def _ReadInitializedOcr(self) -> object:
        if self._ocr is None:
            raise ProductOcrError("PaddleOCR engine is not initialized.")

        return self._ocr

    def _CreateOcr(self) -> object:
        try:
            from paddleocr import PaddleOCR
        except ImportError as error:
            raise ProductOcrError(
                "paddleocr package is required for PaddleOcrEngine."
            ) from error

        return self._CreatePaddleOcr(PaddleOCR)

    def _CreatePaddleOcr(self, paddleOcrClass: object) -> object:
        options: Dict[str, object] = {
            "lang": self._lang,
            "use_doc_orientation_classify": self._useDocOrientationClassify,
            "use_doc_unwarping": self._useDocUnwarping,
            "use_textline_orientation": self._useTextlineOrientation,
            **self._extraOptions,
        }
        if self._device is not None:
            options["device"] = self._device

        try:
            return paddleOcrClass(**options)
        except TypeError:
            legacyOptions: Dict[str, object] = {
                "lang": self._lang,
                "use_angle_cls": self._useTextlineOrientation,
                **self._extraOptions,
            }
            return paddleOcrClass(**legacyOptions)

    def _DecodeImageBytes(self, imageBytes: bytes) -> object:
        return _DecodeImageBytes(imageBytes)

    def _ExtractResultTexts(self, result: object) -> List[str]:
        texts: List[str] = []
        self._CollectTextValues(result, texts)
        return [NormalizeWhiteSpace(text) for text in texts if NormalizeWhiteSpace(text)]

    def _CollectTextValues(self, value: object, texts: List[str]) -> None:
        if value is None:
            return

        if isinstance(value, dict):
            self._CollectTextValuesFromDict(value, texts)
            return

        if isinstance(value, (list, tuple)):
            self._CollectTextValuesFromSequence(value, texts)
            return

        jsonValue = getattr(value, "json", None)
        if isinstance(jsonValue, dict):
            self._CollectTextValuesFromDict(jsonValue, texts)
            return

        if hasattr(value, "to_dict"):
            try:
                dictValue = value.to_dict()
            except Exception:
                dictValue = None
            if isinstance(dictValue, dict):
                self._CollectTextValuesFromDict(dictValue, texts)

    def _CollectTextValuesFromDict(
        self,
        value: Dict[str, object],
        texts: List[str],
    ) -> None:
        for key in ["rec_texts", "texts"]:
            textValues = value.get(key)
            if isinstance(textValues, list):
                texts.extend(item for item in textValues if isinstance(item, str))

        textValue = value.get("text")
        if isinstance(textValue, str):
            texts.append(textValue)

        resultValue = value.get("res")
        if isinstance(resultValue, dict):
            self._CollectTextValuesFromDict(resultValue, texts)

    def _CollectTextValuesFromSequence(
        self,
        value: object,
        texts: List[str],
    ) -> None:
        if self._LooksLegacyOcrLine(value):
            textValue = value[1][0]
            if isinstance(textValue, str):
                texts.append(textValue)
            return

        for item in value:
            self._CollectTextValues(item, texts)

    def _LooksLegacyOcrLine(self, value: object) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[1], (list, tuple))
            and len(value[1]) >= 1
            and isinstance(value[1][0], str)
        )

    def _ExtractTextRegions(self, result: object) -> List[ProductOcrTextRegion]:
        regions: List[ProductOcrTextRegion] = []
        self._CollectTextRegions(result, regions)
        return list(dict.fromkeys(regions))

    def _CollectTextRegions(
        self,
        value: object,
        regions: List[ProductOcrTextRegion],
    ) -> None:
        if value is None:
            return
        if isinstance(value, Mapping):
            self._CollectTextRegionsFromMapping(value, regions)
            return
        if isinstance(value, (list, tuple)):
            if self._LooksLegacyOcrLine(value):
                bounds = _ReadBox(value[0])
                text = NormalizeWhiteSpace(value[1][0])
                if bounds is not None and text:
                    regions.append(
                        ProductOcrTextRegion(
                            text=text,
                            bounds=tuple(round(item) for item in bounds),
                        )
                    )
                return
            for item in value:
                self._CollectTextRegions(item, regions)
            return

        jsonValue = getattr(value, "json", None)
        if isinstance(jsonValue, Mapping):
            self._CollectTextRegionsFromMapping(jsonValue, regions)
            return
        if hasattr(value, "to_dict"):
            try:
                dictValue = value.to_dict()
            except Exception:
                dictValue = None
            if isinstance(dictValue, Mapping):
                self._CollectTextRegionsFromMapping(dictValue, regions)

    def _CollectTextRegionsFromMapping(
        self,
        value: Mapping[str, object],
        regions: List[ProductOcrTextRegion],
    ) -> None:
        textValues = value.get("rec_texts")
        if textValues is None:
            textValues = value.get("texts")
        boxValues = value.get("rec_boxes")
        if boxValues is None:
            boxValues = value.get("rec_polys")
        if boxValues is None:
            boxValues = value.get("dt_polys")
        if isinstance(textValues, Sequence) and boxValues is not None:
            for textValue, boxValue in zip(textValues, boxValues):
                if not isinstance(textValue, str):
                    continue
                bounds = _ReadBox(boxValue)
                normalizedText = NormalizeWhiteSpace(textValue)
                if bounds is None or normalizedText == "":
                    continue
                regions.append(
                    ProductOcrTextRegion(
                        text=normalizedText,
                        bounds=tuple(round(item) for item in bounds),
                    )
                )
        nestedValue = value.get("res")
        if isinstance(nestedValue, Mapping):
            self._CollectTextRegionsFromMapping(nestedValue, regions)


class ProductStructuredOcrEngine(ProductOcrEngine):
    """PP-Structure 표 영역에서 VLM 행을 추출하고 교차 검증한다."""

    def __init__(
        self,
        device: Optional[str] = None,
        useDocOrientationClassify: bool = False,
        useDocUnwarping: bool = False,
        vlExtraOptions: Optional[Dict[str, object]] = None,
        tableExtraOptions: Optional[Dict[str, object]] = None,
        useImageTiling: bool = True,
        useProjectionTiling: bool = True,
        maxTileHeightPixels: int = 2400,
        maxTileSidePixels: int = 4000,
        tileOverlapPixels: int = 240,
        allowHardCutFallback: bool = False,
        tableCropPaddingPixels: int = 24,
        enableDirectTableRecognitionDiagnostic: bool = False,
        vlPipeline: object = None,
        tablePipeline: object = None,
    ) -> None:
        self._device = device
        self._useDocOrientationClassify = useDocOrientationClassify
        self._useDocUnwarping = useDocUnwarping
        self._vlExtraOptions = dict(vlExtraOptions or {})
        self._tableExtraOptions = dict(tableExtraOptions or {})
        self._tableCropPaddingPixels = max(0, tableCropPaddingPixels)
        self._enableDirectTableRecognitionDiagnostic = (
            enableDirectTableRecognitionDiagnostic
        )
        self._tilePlanner = ProductOcrImageTilePlanner(
            useImageTiling=useImageTiling,
            useProjectionTiling=useProjectionTiling,
            maxTileHeightPixels=maxTileHeightPixels,
            maxTileSidePixels=maxTileSidePixels,
            tileOverlapPixels=tileOverlapPixels,
            allowHardCutFallback=allowHardCutFallback,
        )
        self._vlPipeline = vlPipeline
        self._tablePipeline = tablePipeline

    def ExtractTextFromImage(self, imageBytes: bytes) -> str:
        return self.ExtractStructuredTextFromImage(imageBytes).text

    def ExtractStructuredTextFromImage(
        self,
        imageBytes: bytes,
    ) -> ProductStructuredOcrResult:
        image = _DecodeImageBytes(imageBytes)
        tilePlan = self._tilePlanner.BuildTilePlan(image)
        warnings: List[str] = list(tilePlan.warnings)
        rawTileTexts: List[ProductOcrTileTextResult] = []
        successfulVlTileCount = 0
        tableCandidates: List[ProductOcrTableCandidate] = []
        layoutDiagnostics: List[ProductTableLayoutDiagnostic] = []
        tablesWithBounds: List[
            Tuple[ProductOcrTableResult, Tuple[int, int, int, int]]
        ] = []
        for tile in tilePlan.tiles:
            try:
                detectedTableInputs, layoutDiagnostic = (
                    self._BuildDetectedTableInputs(tile)
                )
            except Exception as error:
                warnings.append(
                    "table_layout_detection_failed tile={0}: {1}".format(
                        tile.tileIndex or 1,
                        error,
                    )
                )
                detectedTableInputs = []
                imageHeight, imageWidth = tile.image.shape[:2]
                layoutDiagnostic = ProductTableLayoutDiagnostic(
                    tileIndex=tile.tileIndex,
                    tileOriginX=tile.originX,
                    tileOriginY=tile.originY,
                    imageWidth=imageWidth,
                    imageHeight=imageHeight,
                    error="{0}: {1}".format(type(error).__name__, error),
                )
            layoutDiagnostics.append(layoutDiagnostic)
            if detectedTableInputs:
                warnings.append(
                    "table_layout_detected tile={0} count={1}".format(
                        tile.tileIndex or 1,
                        len(detectedTableInputs),
                    )
                )
            else:
                warnings.append(
                    "table_layout_not_detected tile={0}".format(
                        tile.tileIndex or 1,
                    )
                )
                detectedTableInputs = [(tile, None, None)]

            for vlTile, detectedBounds, recognitionPayload in detectedTableInputs:
                try:
                    rawText, tableBlocks = self._ExtractVlTile(vlTile)
                except Exception as error:
                    warnings.append(
                        "structured_vlm_failed tile={0}: {1}".format(
                            tile.tileIndex or 1,
                            error,
                        )
                    )
                    continue
                successfulVlTileCount += 1
                if rawText:
                    rawTileTexts.append(
                        ProductOcrTileTextResult(
                            tileIndex=tile.tileIndex,
                            text=rawText,
                        )
                    )
                for tableBlock in tableBlocks:
                    localizedBlock = dict(tableBlock)
                    if detectedBounds is not None:
                        localizedBlock.update(
                            {
                                "block_bbox": list(detectedBounds),
                                "bounds_inferred": False,
                                "localization_source": (
                                    "table_recognition_v2_layout"
                                ),
                            }
                        )
                    tableIndex = len(tableCandidates) + 1
                    tableCandidate = self._BuildTableCandidate(
                        tile,
                        localizedBlock,
                        tableIndex=tableIndex,
                    )
                    tableResult, originalBounds, validationWarning = (
                        self._BuildTableResultFromVlBlock(
                            tile,
                            localizedBlock,
                            tableIndex=tableIndex,
                            verifiedPayload=recognitionPayload,
                        )
                    )
                    if validationWarning is not None:
                        warnings.append(validationWarning)
                    if tableResult is None or originalBounds is None:
                        issue = (
                            "invalid_table_html"
                            if validationWarning is not None
                            and "table_invalid" in validationWarning
                            else "invalid_table_bbox"
                        )
                        tableCandidates.append(
                            tableCandidate.model_copy(
                                update={
                                    "validationStatus": "rejected",
                                    "localizationStatus": (
                                        tableCandidate.localizationStatus
                                        if issue == "invalid_table_html"
                                        else "invalid"
                                    ),
                                    "validationIssues": [issue],
                                }
                            )
                        )
                        continue
                    if self._IsDuplicateTable(
                        tablesWithBounds,
                        tableResult,
                        originalBounds,
                    ):
                        tableCandidates.append(
                            tableCandidate.model_copy(
                                update={
                                    "localizationStatus": (
                                        self._ReadLocalizationStatus(localizedBlock)
                                    ),
                                    "validationStatus": "rejected",
                                    "validationIssues": [
                                        "duplicate_table_candidate"
                                    ],
                                }
                            )
                        )
                        continue
                    isVerified = tableResult.validationStatus == "verified"
                    tableCandidates.append(
                        tableCandidate.model_copy(
                            update={
                                "localizationStatus": (
                                    self._ReadLocalizationStatus(localizedBlock)
                                ),
                                "validationStatus": (
                                    "structure_verified"
                                    if isVerified
                                    else "rejected"
                                ),
                                "validationIssues": list(
                                    tableResult.validationIssues
                                ),
                                "tableRecognitionEvidence": (
                                    tableResult.tableRecognitionEvidence
                                ),
                            }
                        )
                    )
                    if isVerified:
                        tablesWithBounds.append((tableResult, originalBounds))

        tables = [
            table.model_copy(update={"tableIndex": tableIndex})
            for tableIndex, (table, _) in enumerate(tablesWithBounds, start=1)
        ]
        rawText = self._BuildRawTileText(rawTileTexts)
        tableText = self._BuildStructuredTableText(tables)
        if tableText:
            return ProductStructuredOcrResult(
                text=self._BuildMergedStructuredAndRawText(tableText, rawText),
                structuredText=tableText,
                rawText=rawText,
                textMergeMode="structured_plus_raw",
                rawTileTexts=rawTileTexts,
                usedStructuredTables=True,
                tables=tables,
                tableCandidates=tableCandidates,
                layoutDiagnostics=layoutDiagnostics,
                warnings=warnings,
            )

        return self._BuildRawFallbackResult(
            rawText,
            rawTileTexts,
            fallbackReason=(
                "structured_vlm_failed"
                if successfulVlTileCount == 0
                else "table_candidates_rejected"
                if tableCandidates
                else "no_table_detected"
            ),
            tableCandidates=tableCandidates,
            layoutDiagnostics=layoutDiagnostics,
            warnings=warnings,
        )

    def BuildArtifactImageTiles(
        self,
        imageBytes: bytes,
    ) -> List[Tuple[Optional[int], bytes]]:
        image = _DecodeImageBytes(imageBytes)
        tiles = self._tilePlanner.BuildTilePlan(image).tiles
        if len(tiles) == 1 and tiles[0].tileIndex is None:
            return [(None, imageBytes)]
        return [
            (tile.tileIndex, _EncodeImageBytes(tile.image, ".jpg"))
            for tile in tiles
        ]

    def _BuildRawFallbackResult(
        self,
        rawText: str,
        rawTileTexts: List[ProductOcrTileTextResult],
        fallbackReason: str,
        tableCandidates: List[ProductOcrTableCandidate],
        layoutDiagnostics: List[ProductTableLayoutDiagnostic],
        warnings: List[str],
    ) -> ProductStructuredOcrResult:
        return ProductStructuredOcrResult(
            text=rawText,
            rawText=rawText,
            textMergeMode="raw_only",
            rawTileTexts=rawTileTexts,
            fallbackReason=fallbackReason,
            tableCandidates=tableCandidates,
            layoutDiagnostics=layoutDiagnostics,
            warnings=list(warnings),
        )

    def _BuildDetectedTableInputs(
        self,
        tile: ProductOcrImageTile,
    ) -> Tuple[
        List[
            Tuple[
                ProductOcrImageTile,
                Optional[Tuple[int, int, int, int]],
                Optional[Mapping[str, object]],
            ]
        ],
        ProductTableLayoutDiagnostic,
    ]:
        output = self._ReadInitializedTablePipeline().predict(
            tile.image,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_layout_detection=True,
            use_ocr_model=True,
        )
        detectedInputs: List[
            Tuple[
                ProductOcrImageTile,
                Optional[Tuple[int, int, int, int]],
                Optional[Mapping[str, object]],
            ]
        ] = []
        layoutRegions: List[ProductTableLayoutRegion] = []
        layoutPayloadAvailable = False
        rawRegionCount = 0
        parseIssues: List[str] = []
        imageHeight, imageWidth = tile.image.shape[:2]
        for result in output:
            payload = self._ReadResultPayload(result)
            layoutPayload = payload.get("layout_det_res")
            if not isinstance(layoutPayload, Mapping):
                continue
            layoutPayloadAvailable = True
            layoutBoxes = layoutPayload.get("boxes", [])
            if not isinstance(layoutBoxes, list):
                parseIssues.append("invalid_layout_boxes")
                layoutBoxes = []
            rawRegionCount += len(layoutBoxes)
            tablePayloads = payload.get("table_res_list")
            tablePayloadList = (
                tablePayloads if isinstance(tablePayloads, list) else []
            )
            tablePayloadIndex = 0
            for layoutBox in layoutBoxes:
                if not isinstance(layoutBox, Mapping):
                    continue
                rawLabel = layoutBox.get("label")
                label = rawLabel.strip() if isinstance(rawLabel, str) else ""
                reportedBounds = self._ReadBox(layoutBox.get("coordinate"))
                score = self._ReadOptionalFloat(layoutBox.get("score"))
                if label.lower() != "table":
                    layoutRegions.append(
                        ProductTableLayoutRegion(
                            label=label,
                            score=score,
                            reportedBounds=reportedBounds,
                            issues=["label_not_table"],
                        )
                    )
                    continue
                tablePayload = (
                    tablePayloadList[tablePayloadIndex]
                    if tablePayloadIndex < len(tablePayloadList)
                    and isinstance(tablePayloadList[tablePayloadIndex], Mapping)
                    else {}
                )
                tablePayloadIndex += 1
                if reportedBounds is None:
                    layoutRegions.append(
                        ProductTableLayoutRegion(
                            label=label,
                            score=score,
                            issues=["invalid_bounds"],
                            recognitionPayloadAvailable=bool(tablePayload),
                        )
                    )
                    continue
                localBounds = (
                    floor(reportedBounds[0]),
                    floor(reportedBounds[1]),
                    ceil(reportedBounds[2]),
                    ceil(reportedBounds[3]),
                )
                cropResult = self._BuildTableCrop(tile, localBounds)
                if cropResult is None:
                    layoutRegions.append(
                        ProductTableLayoutRegion(
                            label=label,
                            score=score,
                            reportedBounds=reportedBounds,
                            recognitionPayloadAvailable=bool(tablePayload),
                            issues=["invalid_crop_bounds"],
                        )
                    )
                    continue
                tableCrop, _ = cropResult
                cropBounds = (
                    max(0, localBounds[0] - self._tableCropPaddingPixels),
                    max(0, localBounds[1] - self._tableCropPaddingPixels),
                    min(
                        imageWidth,
                        localBounds[2] + self._tableCropPaddingPixels,
                    ),
                    min(
                        imageHeight,
                        localBounds[3] + self._tableCropPaddingPixels,
                    ),
                )
                layoutRegions.append(
                    ProductTableLayoutRegion(
                        label=label,
                        score=score,
                        reportedBounds=reportedBounds,
                        cropBounds=cropBounds,
                        selectedForVlm=True,
                        recognitionPayloadAvailable=bool(tablePayload),
                        issues=(
                            []
                            if tablePayload
                            else ["recognition_payload_unavailable"]
                        ),
                    )
                )
                detectedInputs.append(
                    (
                        ProductOcrImageTile(
                            tileIndex=tile.tileIndex,
                            image=tableCrop,
                        ),
                        localBounds,
                        self._NormalizeDetectedTablePayload(
                            tablePayload,
                            localBounds,
                        ),
                    )
                )
        if not layoutPayloadAvailable:
            parseIssues.append("layout_payload_unavailable")
        elif rawRegionCount == 0 and not parseIssues:
            parseIssues.append("no_layout_boxes")
        directRecognitionAttempted = False
        directRecognitionPayloadCount = 0
        directRecognitionTables: List[ProductTableRecognitionEvidence] = []
        directRecognitionError: Optional[str] = None
        if (
            not detectedInputs
            and self._enableDirectTableRecognitionDiagnostic
        ):
            directRecognitionAttempted = True
            (
                directRecognitionPayloadCount,
                directRecognitionTables,
                directRecognitionError,
            ) = self._ReadDirectTableRecognitionDiagnostic(tile.image)
        return detectedInputs, ProductTableLayoutDiagnostic(
            tileIndex=tile.tileIndex,
            tileOriginX=tile.originX,
            tileOriginY=tile.originY,
            imageWidth=imageWidth,
            imageHeight=imageHeight,
            layoutPayloadAvailable=layoutPayloadAvailable,
            rawRegionCount=rawRegionCount,
            regions=layoutRegions,
            parseIssues=list(dict.fromkeys(parseIssues)),
            directRecognitionAttempted=directRecognitionAttempted,
            directRecognitionPayloadCount=directRecognitionPayloadCount,
            directRecognitionTables=directRecognitionTables,
            directRecognitionError=directRecognitionError,
        )

    def _ReadDirectTableRecognitionDiagnostic(
        self,
        image: object,
    ) -> Tuple[int, List[ProductTableRecognitionEvidence], Optional[str]]:
        try:
            output = self._ReadInitializedTablePipeline().predict(
                image,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_layout_detection=False,
                use_ocr_model=True,
            )
            payloadCount = 0
            tables: List[ProductTableRecognitionEvidence] = []
            for result in output:
                payload = self._ReadResultPayload(result)
                tablePayloads = payload.get("table_res_list")
                if not isinstance(tablePayloads, list):
                    continue
                payloadCount += len(tablePayloads)
                tables.extend(
                    self._BuildTableRecognitionEvidence(tablePayload).model_copy(
                        update={"sourceName": "table_recognition_v2_direct"}
                    )
                    for tablePayload in tablePayloads
                    if isinstance(tablePayload, Mapping)
                )
            return payloadCount, tables, None
        except Exception as error:
            return 0, [], "{0}: {1}".format(type(error).__name__, error)

    def _ReadOptionalFloat(self, value: object) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _NormalizeDetectedTablePayload(
        self,
        payload: Mapping[str, object],
        tableBounds: Tuple[int, int, int, int],
    ) -> Mapping[str, object]:
        normalizedPayload = dict(payload)
        rawCellBounds = payload.get("cell_box_list")
        cellBoundValues = rawCellBounds if isinstance(rawCellBounds, list) else []
        cropLeft = max(
            0,
            tableBounds[0] - self._tableCropPaddingPixels,
        )
        cropTop = max(
            0,
            tableBounds[1] - self._tableCropPaddingPixels,
        )
        normalizedPayload["cell_box_list"] = [
            [
                bounds[0] - cropLeft,
                bounds[1] - cropTop,
                bounds[2] - cropLeft,
                bounds[3] - cropTop,
            ]
            for rawCellBound in cellBoundValues
            if (bounds := self._ReadBox(rawCellBound)) is not None
        ]
        return normalizedPayload

    def _ReadInitializedVlPipeline(self) -> object:
        if self._vlPipeline is not None:
            return self._vlPipeline

        try:
            from paddleocr import PaddleOCRVL
        except ImportError as error:
            raise ProductOcrError(
                "paddleocr package with PaddleOCRVL is required."
            ) from error

        options: Dict[str, object] = {
            "pipeline_version": "v1.6",
            "use_layout_detection": True,
            "use_chart_recognition": False,
            "use_seal_recognition": False,
            "use_ocr_for_image_block": True,
            "use_doc_orientation_classify": self._useDocOrientationClassify,
            "use_doc_unwarping": self._useDocUnwarping,
            "format_block_content": False,
            "use_queues": False,
            **self._vlExtraOptions,
        }
        if self._device is not None:
            options["device"] = self._device
        self._vlPipeline = PaddleOCRVL(**options)
        return self._vlPipeline

    def _ExtractVlTile(
        self,
        tile: ProductOcrImageTile,
    ) -> Tuple[str, List[Mapping[str, object]]]:
        output = self._ReadInitializedVlPipeline().predict(tile.image)
        markdownTexts: List[str] = []
        tableBlocks: List[Mapping[str, object]] = []
        blockTexts: List[str] = []
        for result in output:
            payload = self._ReadResultPayload(result)
            isBridgePayload = "bridge_raw_text" in payload
            bridgeRawText = payload.get("bridge_raw_text")
            if isinstance(bridgeRawText, str) and bridgeRawText.strip():
                blockTexts.append(bridgeRawText.strip())
            markdownText = self._ReadMarkdownText(result)
            if markdownText:
                markdownTexts.append(markdownText)
            for block in payload.get("parsing_res_list", []):
                if not isinstance(block, Mapping):
                    continue
                content = block.get("block_content")
                if (
                    not isBridgePayload
                    and isinstance(content, str)
                    and content.strip()
                ):
                    blockTexts.append(content.strip())
                if block.get("block_label") == "table":
                    tableBlocks.append(block)
        rawText = "\n\n".join(markdownTexts or blockTexts)
        return rawText, tableBlocks

    def _BuildRawTileText(
        self,
        rawTileTexts: List[ProductOcrTileTextResult],
    ) -> str:
        return "\n\n".join(
            "[tile {0}]\n{1}".format(
                rawTileText.tileIndex if rawTileText.tileIndex is not None else 1,
                rawTileText.text,
            )
            for rawTileText in rawTileTexts
            if rawTileText.text.strip()
        )

    def _BuildMergedStructuredAndRawText(
        self,
        structuredText: str,
        rawText: str,
    ) -> str:
        if structuredText.strip() and rawText.strip():
            return "[structured_tables]\n{0}\n\n[raw_ocr_tiles]\n{1}".format(
                structuredText,
                rawText,
            )
        return structuredText or rawText

    def _BuildTableResultFromVlBlock(
        self,
        tile: ProductOcrImageTile,
        tableBlock: Mapping[str, object],
        tableIndex: int,
        verifiedPayload: Optional[Mapping[str, object]] = None,
    ) -> Tuple[
        Optional[ProductOcrTableResult],
        Optional[Tuple[int, int, int, int]],
        Optional[str],
    ]:
        vlHtml = tableBlock.get("block_content")
        if not isinstance(vlHtml, str) or not self._LooksLikeTableHtml(vlHtml):
            return None, None, (
                "structured_vlm_table_invalid tile={0} table={1}".format(
                    tile.tileIndex or 1,
                    tableIndex,
                )
            )
        reportedBounds = self._ReadBox(tableBlock.get("block_bbox"))
        cropResult = self._BuildTableCrop(tile, reportedBounds)
        if cropResult is None:
            imageHeight, imageWidth = tile.image.shape[:2]
            boundsText = (
                "none"
                if reportedBounds is None
                else ",".join("{0:g}".format(value) for value in reportedBounds)
            )
            return None, None, (
                "structured_vlm_table_bbox_invalid tile={0} table={1} "
                "image={2}x{3} bbox={4}".format(
                    tile.tileIndex or 1,
                    tableIndex,
                    imageWidth,
                    imageHeight,
                    boundsText,
                )
            )
        tableCrop, originalBounds = cropResult
        cellTexts = self._ExtractTextsFromHtml(vlHtml)
        rawSourceName = tableBlock.get("source_name")
        sourceName = (
            rawSourceName.strip()
            if isinstance(rawSourceName, str) and rawSourceName.strip()
            else "paddleocr_vl_v1_6"
        )
        validationStatus = "unverified"
        validationIssues: List[str] = []
        validationWarning: Optional[str] = None
        tableRecognitionEvidence: Optional[ProductTableRecognitionEvidence] = None
        semanticIssues = self._ValidateNutritionUnits(vlHtml)
        if tableBlock.get("bounds_inferred") is True:
            semanticIssues.append("vlm_table_bounds_inferred_from_tile")
        try:
            if verifiedPayload is None:
                verifiedPayload = self._ReadVerifiedTablePayload(tableCrop)
            tableRecognitionEvidence = self._BuildTableRecognitionEvidence(
                verifiedPayload,
            )
            validationError = self._ValidateVerifiedTablePayload(
                verifiedPayload,
                tableCrop,
            )
            if validationError is None:
                verifiedHtml = str(verifiedPayload.get("pred_html") or "")
                validationIssues = self._CompareTableEvidence(
                    vlHtml,
                    verifiedHtml,
                )
                validationIssues.extend(semanticIssues)
                validationIssues = list(dict.fromkeys(validationIssues))
                if validationIssues:
                    validationWarning = self._BuildValidationWarning(
                        tile,
                        tableIndex,
                        ",".join(validationIssues),
                    )
                else:
                    validationStatus = "verified"
                    sourceName = "{0}+table_recognition_v2_verified".format(
                        sourceName,
                    )
            else:
                validationIssues = [validationError, *semanticIssues]
                validationWarning = self._BuildValidationWarning(
                    tile,
                    tableIndex,
                    validationError,
                )
        except Exception as error:
            validationIssues = [
                NormalizeWhiteSpace(str(error)) or "unknown",
                *semanticIssues,
            ]
            validationWarning = self._BuildValidationWarning(
                tile,
                tableIndex,
                str(error),
            )
        return ProductOcrTableResult(
            tableIndex=tableIndex,
            sourceName=sourceName,
            tableName=self._ReadTableName(tableBlock),
            tileIndex=tile.tileIndex,
            html=vlHtml,
            cellTexts=cellTexts,
            plainText=self._BuildPlainTextFromHtml(vlHtml, cellTexts),
            sourceRows=self._ReadSourceRows(tableBlock),
            validationStatus=validationStatus,
            validationIssues=validationIssues,
            tableRecognitionEvidence=tableRecognitionEvidence,
        ), originalBounds, validationWarning

    def _BuildTableCandidate(
        self,
        tile: ProductOcrImageTile,
        tableBlock: Mapping[str, object],
        tableIndex: int,
    ) -> ProductOcrTableCandidate:
        rawHtml = tableBlock.get("block_content")
        html = rawHtml if isinstance(rawHtml, str) else ""
        cellTexts = self._ExtractTextsFromHtml(html) if html else []
        reportedBounds = self._ReadBox(tableBlock.get("block_bbox"))
        return ProductOcrTableCandidate(
            tableIndex=tableIndex,
            sourceName=self._ReadTableSourceName(tableBlock),
            tableName=self._ReadTableName(tableBlock),
            tileIndex=tile.tileIndex,
            html=html,
            cellTexts=cellTexts,
            plainText=self._BuildPlainTextFromHtml(html, cellTexts),
            sourceRows=self._ReadSourceRows(tableBlock),
            reportedBounds=reportedBounds,
            localizationStatus=(
                self._ReadLocalizationStatus(tableBlock)
                if reportedBounds is not None
                else "invalid"
            ),
        )

    def _ReadTableSourceName(self, tableBlock: Mapping[str, object]) -> str:
        rawSourceName = tableBlock.get("source_name")
        return (
            rawSourceName.strip()
            if isinstance(rawSourceName, str) and rawSourceName.strip()
            else "paddleocr_vl_v1_6"
        )

    def _ReadTableName(self, tableBlock: Mapping[str, object]) -> str:
        rawTableName = tableBlock.get("table_name")
        return (
            NormalizeWhiteSpace(rawTableName)
            if isinstance(rawTableName, str)
            else ""
        )

    def _ReadSourceRows(self, tableBlock: Mapping[str, object]) -> List[str]:
        rawSourceRows = tableBlock.get("source_rows")
        if not isinstance(rawSourceRows, list):
            return []
        return [
            NormalizeWhiteSpace(sourceRow)
            for sourceRow in rawSourceRows
            if isinstance(sourceRow, str) and NormalizeWhiteSpace(sourceRow)
        ]

    def _ReadLocalizationStatus(self, tableBlock: Mapping[str, object]) -> str:
        return "inferred" if tableBlock.get("bounds_inferred") is True else "valid"

    def _BuildTableRecognitionEvidence(
        self,
        payload: Mapping[str, object],
    ) -> ProductTableRecognitionEvidence:
        rawCellBounds = payload.get("cell_box_list")
        cellBounds: List[Tuple[float, float, float, float]] = []
        try:
            cellBoundValues = (
                []
                if isinstance(rawCellBounds, (str, bytes, Mapping))
                else list(rawCellBounds)  # type: ignore[arg-type]
            )
        except TypeError:
            cellBoundValues = []
        for rawCellBound in cellBoundValues:
            bounds = self._ReadBox(rawCellBound)
            if bounds is not None:
                cellBounds.append(bounds)
        html = payload.get("pred_html")
        return ProductTableRecognitionEvidence(
            html=html if isinstance(html, str) else "",
            cellTexts=self._ReadCellTexts(payload),
            cellBounds=cellBounds,
        )

    def _BuildTableCrop(
        self,
        tile: ProductOcrImageTile,
        rawBounds: object,
    ) -> Optional[Tuple[object, Tuple[int, int, int, int]]]:
        bounds = self._ReadBox(rawBounds)
        if bounds is None:
            return None
        imageHeight, imageWidth = tile.image.shape[:2]
        if (
            bounds[0] < 0
            or bounds[1] < 0
            or bounds[2] > imageWidth
            or bounds[3] > imageHeight
            or bounds[2] <= bounds[0]
            or bounds[3] <= bounds[1]
        ):
            return None
        left = max(0, floor(bounds[0]) - self._tableCropPaddingPixels)
        top = max(0, floor(bounds[1]) - self._tableCropPaddingPixels)
        right = min(imageWidth, ceil(bounds[2]) + self._tableCropPaddingPixels)
        bottom = min(imageHeight, ceil(bounds[3]) + self._tableCropPaddingPixels)
        if right <= left or bottom <= top:
            return None
        originalBounds = (
            tile.originX + floor(bounds[0]),
            tile.originY + floor(bounds[1]),
            tile.originX + ceil(bounds[2]),
            tile.originY + ceil(bounds[3]),
        )
        return tile.image[top:bottom, left:right], originalBounds

    def _ReadInitializedTablePipeline(self) -> object:
        if self._tablePipeline is not None:
            return self._tablePipeline
        try:
            from paddleocr import TableRecognitionPipelineV2
        except ImportError as error:
            raise ProductOcrError(
                "paddleocr package with TableRecognitionPipelineV2 is required."
            ) from error
        options: Dict[str, object] = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_layout_detection": True,
            "use_ocr_model": True,
            **self._tableExtraOptions,
        }
        if self._device is not None:
            options["device"] = self._device
        self._tablePipeline = TableRecognitionPipelineV2(**options)
        return self._tablePipeline

    def _ReadVerifiedTablePayload(self, tableCrop: object) -> Mapping[str, object]:
        output = self._ReadInitializedTablePipeline().predict(
            tableCrop,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_layout_detection=False,
            use_ocr_model=True,
        )
        for result in output:
            payload = self._ReadResultPayload(result)
            tableResults = payload.get("table_res_list")
            if isinstance(tableResults, list):
                for tableResult in tableResults:
                    if isinstance(tableResult, Mapping):
                        return tableResult
        return {}

    def _ValidateVerifiedTablePayload(
        self,
        payload: Mapping[str, object],
        tableCrop: object,
    ) -> Optional[str]:
        html = payload.get("pred_html")
        if not isinstance(html, str) or not self._LooksLikeTableHtml(html):
            return "invalid_pred_html"
        cellBoxes = payload.get("cell_box_list")
        if cellBoxes is None:
            return "empty_cell_boxes"
        try:
            if len(cellBoxes) == 0:
                return "empty_cell_boxes"
        except TypeError:
            return "invalid_cell_boxes"
        cropHeight, cropWidth = tableCrop.shape[:2]
        for cellBox in cellBoxes:
            bounds = self._ReadBox(cellBox)
            if bounds is None:
                return "invalid_cell_box"
            if (
                bounds[0] < 0
                or bounds[1] < 0
                or bounds[2] > cropWidth
                or bounds[3] > cropHeight
                or bounds[2] <= bounds[0]
                or bounds[3] <= bounds[1]
            ):
                return "cell_box_out_of_bounds"
        if not self._ReadCellTexts(payload):
            return "empty_cell_texts"
        return None

    def _ReadCellTexts(self, payload: Mapping[str, object]) -> List[str]:
        tableOcrPayload = payload.get("table_ocr_pred")
        if not isinstance(tableOcrPayload, Mapping):
            return []
        rawCellTexts = tableOcrPayload.get("rec_texts")
        if not isinstance(rawCellTexts, list):
            return []
        return [
            NormalizeWhiteSpace(text)
            for text in rawCellTexts
            if isinstance(text, str) and NormalizeWhiteSpace(text)
        ]

    def _ReadResultPayload(self, result: object) -> Mapping[str, object]:
        jsonPayload = getattr(result, "json", None)
        payload = jsonPayload if isinstance(jsonPayload, Mapping) else result
        if not isinstance(payload, Mapping):
            return {}
        nestedPayload = payload.get("res")
        return nestedPayload if isinstance(nestedPayload, Mapping) else payload

    def _ReadMarkdownText(self, result: object) -> str:
        markdown = getattr(result, "markdown", None)
        if isinstance(markdown, str):
            return markdown.strip()
        if not isinstance(markdown, Mapping):
            return ""
        markdownTexts = markdown.get("markdown_texts")
        if isinstance(markdownTexts, str):
            return markdownTexts.strip()
        if isinstance(markdownTexts, list):
            return "\n\n".join(
                text.strip()
                for text in markdownTexts
                if isinstance(text, str) and text.strip()
            )
        return ""

    def _ReadBox(self, value: object) -> Optional[Tuple[float, float, float, float]]:
        return _ReadBox(value)

    def _IsDuplicateTable(
        self,
        tablesWithBounds: List[
            Tuple[ProductOcrTableResult, Tuple[int, int, int, int]]
        ],
        candidate: ProductOcrTableResult,
        candidateBounds: Tuple[int, int, int, int],
    ) -> bool:
        candidateText = NormalizeWhiteSpace(candidate.plainText)
        for table, bounds in tablesWithBounds:
            if candidateText and candidateText == NormalizeWhiteSpace(table.plainText):
                return True
            if self._BuildIntersectionOverUnion(bounds, candidateBounds) >= 0.65:
                return True
        return False

    def _BuildIntersectionOverUnion(
        self,
        left: Tuple[int, int, int, int],
        right: Tuple[int, int, int, int],
    ) -> float:
        intersectionWidth = max(0, min(left[2], right[2]) - max(left[0], right[0]))
        intersectionHeight = max(0, min(left[3], right[3]) - max(left[1], right[1]))
        intersectionArea = intersectionWidth * intersectionHeight
        leftArea = max(0, left[2] - left[0]) * max(0, left[3] - left[1])
        rightArea = max(0, right[2] - right[0]) * max(0, right[3] - right[1])
        unionArea = leftArea + rightArea - intersectionArea
        return intersectionArea / unionArea if unionArea else 0.0

    def _BuildValidationWarning(
        self,
        tile: ProductOcrImageTile,
        tableIndex: int,
        reason: str,
    ) -> str:
        return "table_validation_failed tile={0} table={1} reason={2}".format(
            tile.tileIndex or 1,
            tableIndex,
            NormalizeWhiteSpace(reason) or "unknown",
        )

    def _CompareTableEvidence(
        self,
        vlHtml: str,
        verifiedHtml: str,
    ) -> List[str]:
        vlTokens = self._ExtractQuantityTokens(
            self._BuildPlainTextFromHtml(vlHtml, []),
        )
        verifiedTokens = self._ExtractQuantityTokens(
            self._BuildPlainTextFromHtml(verifiedHtml, []),
        )
        if not vlTokens or not verifiedTokens:
            return ["quantity_evidence_unavailable"]

        issues: List[str] = []
        vlUnitsByValue = self._BuildUnitsByValue(vlTokens)
        verifiedUnitsByValue = self._BuildUnitsByValue(verifiedTokens)
        for value in vlUnitsByValue.keys() & verifiedUnitsByValue.keys():
            if not (vlUnitsByValue[value] & verifiedUnitsByValue[value]):
                issues.append("unit_conflict:{0}".format(value))

        overlapCount = len(vlTokens & verifiedTokens)
        minimumComparableCount = min(len(vlTokens), len(verifiedTokens))
        if overlapCount == 0 or overlapCount * 2 < minimumComparableCount:
            issues.append("quantity_mismatch")
        return list(dict.fromkeys(issues))

    def _ExtractQuantityTokens(self, text: str) -> set[Tuple[str, str]]:
        matches = re.findall(
            r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(mg|g|kg|ml|l|%|kcal|㎎|㎏|㎖)",
            text,
            flags=re.IGNORECASE,
        )
        unitAliases = {"㎎": "mg", "㎏": "kg", "㎖": "ml"}
        return {
            (
                value.replace(",", ""),
                unitAliases.get(unit.lower(), unit.lower()),
            )
            for value, unit in matches
        }

    def _BuildUnitsByValue(
        self,
        tokens: set[Tuple[str, str]],
    ) -> Dict[str, set[str]]:
        unitsByValue: Dict[str, set[str]] = {}
        for value, unit in tokens:
            unitsByValue.setdefault(value, set()).add(unit)
        return unitsByValue

    def _ValidateNutritionUnits(self, html: str) -> List[str]:
        expectedUnits = {
            "나트륨": {"mg"},
            "콜레스테롤": {"mg"},
            "탄수화물": {"g"},
            "당류": {"g"},
            "지방": {"g"},
            "트랜스지방": {"g"},
            "포화지방": {"g"},
            "단백질": {"g"},
        }
        parser = _HtmlTableExtractor()
        parser.feed(html)
        issues: List[str] = []
        for row in parser.rows:
            if len(row) < 2:
                continue
            normalizedLabel = NormalizeWhiteSpace(row[0]).replace(" ", "")
            rowTokens = self._ExtractQuantityTokens(" ".join(row[1:]))
            for label, allowedUnits in expectedUnits.items():
                if label not in normalizedLabel:
                    continue
                unexpectedUnits = {
                    unit
                    for _, unit in rowTokens
                    if unit not in allowedUnits and unit != "%"
                }
                issues.extend(
                    "nutrition_unit_mismatch:{0}:{1}".format(label, unit)
                    for unit in sorted(unexpectedUnits)
                )
                break
        return issues

    def _ExtractTextsFromHtml(self, html: str) -> List[str]:
        parser = _HtmlTableExtractor()
        parser.feed(html)
        return [cell for row in parser.rows for cell in row]

    def _BuildPlainTextFromHtml(
        self,
        html: str,
        fallbackCellTexts: List[str],
    ) -> str:
        parser = _HtmlTableExtractor()
        parser.feed(html)
        if parser.rows:
            return "\n".join(" | ".join(row) for row in parser.rows)
        return "\n".join(fallbackCellTexts)

    def _LooksLikeTableHtml(self, html: str) -> bool:
        loweredHtml = html.lower()
        return (
            "<table" in loweredHtml
            and "<tr" in loweredHtml
            and ("<td" in loweredHtml or "<th" in loweredHtml)
        )

    def _BuildStructuredTableText(
        self,
        tables: List[ProductOcrTableResult],
    ) -> str:
        tableTexts = []
        for table in tables:
            if not table.plainText.strip():
                continue
            tableTexts.append(
                "[table {0}]\n{1}".format(
                    table.tableIndex,
                    table.plainText,
                )
            )
        return "\n\n".join(tableTexts)

class _HtmlTableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: List[List[str]] = []
        self._currentRow: List[str] = []
        self._currentCellParts: List[str] = []
        self._insideCell = False

    def handle_starttag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        del attrs
        if tag.lower() == "tr":
            self._currentRow = []
        elif tag.lower() in {"td", "th"}:
            self._insideCell = True
            self._currentCellParts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"}:
            cellText = NormalizeWhiteSpace(" ".join(self._currentCellParts))
            self._currentRow.append(cellText)
            self._currentCellParts = []
            self._insideCell = False
        elif tag.lower() == "tr" and any(self._currentRow):
            self.rows.append(list(self._currentRow))
            self._currentRow = []

    def handle_data(self, data: str) -> None:
        normalizedText = NormalizeWhiteSpace(data)
        if self._insideCell and normalizedText:
            self._currentCellParts.append(normalizedText)


def BuildTableGroundingDiagnostics(
    tableCandidates: Sequence[ProductOcrTableCandidate],
    textRegions: Sequence[ProductOcrTextRegion],
) -> List[ProductOcrTableGroundingDiagnostic]:
    """VLM 후보 row를 screening OCR 근거와 비교하되 승인에는 사용하지 않는다."""

    return [
        _BuildTableGroundingDiagnostic(tableCandidate, textRegions)
        for tableCandidate in tableCandidates
    ]


def _BuildTableGroundingDiagnostic(
    tableCandidate: ProductOcrTableCandidate,
    textRegions: Sequence[ProductOcrTextRegion],
) -> ProductOcrTableGroundingDiagnostic:
    parser = _HtmlTableExtractor()
    parser.feed(tableCandidate.html)
    rows: List[ProductOcrTableRowGroundingDiagnostic] = []
    for rowIndex, rowCells in enumerate(parser.rows, start=1):
        cells = [
            _BuildCellGroundingDiagnostic(
                cellIndex=cellIndex,
                role="key" if cellIndex == 1 else "value",
                text=cellText,
                textRegions=textRegions,
            )
            for cellIndex, cellText in enumerate(rowCells, start=1)
            if NormalizeWhiteSpace(cellText)
        ]
        grounded = bool(cells) and all(cell.status == "grounded" for cell in cells)
        issues = [
            "cell_{0}_{1}".format(cell.cellIndex, issue)
            for cell in cells
            for issue in cell.issues
        ]
        if not cells:
            issues.append("empty_row")
        rows.append(
            ProductOcrTableRowGroundingDiagnostic(
                rowIndex=rowIndex,
                sourceText=(
                    tableCandidate.sourceRows[rowIndex - 1]
                    if rowIndex <= len(tableCandidate.sourceRows)
                    else ""
                ),
                status="grounded" if grounded else "rejected",
                derivedBounds=_BuildRegionUnion(
                    [
                        region.bounds
                        for cell in cells
                        for region in cell.matchedRegions
                    ]
                ),
                cells=cells,
                issues=list(dict.fromkeys(issues)),
            )
        )

    groundedRowCount = sum(row.status == "grounded" for row in rows)
    status = (
        "grounded"
        if rows and groundedRowCount == len(rows)
        else "partial"
        if groundedRowCount > 0
        else "rejected"
    )
    return ProductOcrTableGroundingDiagnostic(
        tableIndex=tableCandidate.tableIndex,
        sourceName=tableCandidate.sourceName,
        tableName=tableCandidate.tableName,
        status=status,
        rowCount=len(rows),
        groundedRowCount=groundedRowCount,
        rejectedRowCount=len(rows) - groundedRowCount,
        derivedBounds=_BuildRegionUnion(
            [row.derivedBounds for row in rows if row.derivedBounds is not None]
        ),
        rows=rows,
    )


def _BuildCellGroundingDiagnostic(
    cellIndex: int,
    role: str,
    text: str,
    textRegions: Sequence[ProductOcrTextRegion],
) -> ProductOcrCellGroundingDiagnostic:
    normalizedText = _NormalizeGroundingText(text)
    textTokens = _ExtractGroundingTextTokens(text)
    numericTokens = _ExtractGroundingNumericTokens(text)
    matches = _FindGroundingRegionMatches(
        normalizedText,
        textTokens,
        numericTokens,
        textRegions,
    )
    matchedTexts = [match.text for match in matches]
    textCoverage = _CalculateGroundingCoverage(normalizedText, matchedTexts)
    missingTextTokens = [
        token
        for token in textTokens
        if not _IsGroundingTextTokenSupported(token, matchedTexts)
    ]
    matchedNumericTokens = {
        token
        for matchedText in matchedTexts
        for token in _ExtractGroundingNumericTokens(matchedText)
    }
    missingNumericTokens = [
        token for token in numericTokens if token not in matchedNumericTokens
    ]
    issues: List[str] = []
    if not matches:
        issues.append("no_ocr_region_match")
    if textCoverage < TABLE_GROUNDING_TEXT_COVERAGE_THRESHOLD:
        issues.append(
            "text_coverage_below_{0:g}".format(
                TABLE_GROUNDING_TEXT_COVERAGE_THRESHOLD,
            )
        )
    if missingTextTokens:
        issues.append(
            "text_tokens_missing:{0}".format(",".join(missingTextTokens))
        )
    if missingNumericTokens:
        issues.append(
            "numeric_tokens_missing:{0}".format(",".join(missingNumericTokens))
        )
    return ProductOcrCellGroundingDiagnostic(
        cellIndex=cellIndex,
        role=role,
        text=NormalizeWhiteSpace(text),
        status="grounded" if not issues else "rejected",
        textCoverage=round(textCoverage, 4),
        textTokens=textTokens,
        missingTextTokens=missingTextTokens,
        numericTokens=numericTokens,
        missingNumericTokens=missingNumericTokens,
        matchedRegions=matches,
        issues=issues,
    )


def _FindGroundingRegionMatches(
    normalizedText: str,
    textTokens: Sequence[str],
    numericTokens: Sequence[str],
    textRegions: Sequence[ProductOcrTextRegion],
) -> List[ProductOcrRegionGroundingMatch]:
    if not normalizedText:
        return []
    matches: List[ProductOcrRegionGroundingMatch] = []
    for regionIndex, region in enumerate(textRegions, start=1):
        normalizedRegionText = _NormalizeGroundingText(region.text)
        if not normalizedRegionText:
            continue
        score = _BuildGroundingMatchScore(normalizedText, normalizedRegionText)
        regionNumericTokens = set(_ExtractGroundingNumericTokens(region.text))
        hasNumericEvidence = bool(set(numericTokens) & regionNumericTokens)
        hasTextEvidence = any(
            _IsGroundingTextTokenSupported(token, [region.text])
            for token in textTokens
            if len(token) >= 2
        )
        isShortText = len(normalizedText) <= 3
        isMatch = (
            hasNumericEvidence or hasTextEvidence
            if isShortText
            else normalizedText in normalizedRegionText
            or normalizedRegionText in normalizedText
            or score >= TABLE_GROUNDING_TEXT_COVERAGE_THRESHOLD
            or hasNumericEvidence
            or hasTextEvidence
        )
        if not isMatch:
            continue
        matches.append(
            ProductOcrRegionGroundingMatch(
                regionIndex=regionIndex,
                text=region.text,
                bounds=region.bounds,
                matchScore=round(score, 4),
            )
        )
    return matches


def _BuildGroundingMatchScore(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    longestMatch = matcher.find_longest_match().size
    return max(matcher.ratio(), longestMatch / min(len(left), len(right)))


def _CalculateGroundingCoverage(
    normalizedText: str,
    matchedTexts: Sequence[str],
) -> float:
    if not normalizedText:
        return 0.0
    coveredCharacters = [False] * len(normalizedText)
    minimumMatchLength = 1 if len(normalizedText) <= 3 else 2
    for matchedText in matchedTexts:
        normalizedMatchedText = _NormalizeGroundingText(matchedText)
        for match in SequenceMatcher(
            None,
            normalizedText,
            normalizedMatchedText,
            autojunk=False,
        ).get_matching_blocks():
            if match.size < minimumMatchLength:
                continue
            for characterIndex in range(match.a, match.a + match.size):
                coveredCharacters[characterIndex] = True
    return sum(coveredCharacters) / len(coveredCharacters)


def _ExtractGroundingTextTokens(text: str) -> List[str]:
    normalizedText = unicodedata.normalize("NFKC", text or "").lower()
    unitTokens = {"g", "kg", "mg", "l", "ml", "kcal"}
    return list(
        dict.fromkeys(
            token
            for token in re.findall(r"[a-z]+|[가-힣]+", normalizedText)
            if token not in unitTokens
        )
    )


def _ExtractGroundingNumericTokens(text: str) -> List[str]:
    normalizedText = unicodedata.normalize("NFKC", text or "").lower()
    matches = re.findall(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(mg|g|kg|ml|l|%|kcal)?",
        normalizedText,
    )
    return list(
        dict.fromkeys(
            "{0}:{1}".format(value.replace(",", ""), unit or "#")
            for value, unit in matches
        )
    )


def _IsGroundingTextTokenSupported(
    token: str,
    matchedTexts: Sequence[str],
) -> bool:
    for matchedText in matchedTexts:
        normalizedMatchedText = _NormalizeGroundingText(matchedText)
        regionTokens = _ExtractGroundingTextTokens(matchedText)
        if len(token) <= 2:
            if token in regionTokens:
                return True
            continue
        if token in normalizedMatchedText:
            return True
        if any(
            SequenceMatcher(None, token, regionToken, autojunk=False).ratio()
            >= TABLE_GROUNDING_TOKEN_SIMILARITY_THRESHOLD
            for regionToken in regionTokens
        ):
            return True
    return False


def _NormalizeGroundingText(text: str) -> str:
    normalizedText = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(character for character in normalizedText if character.isalnum())


def _BuildRegionUnion(
    boundsValues: Sequence[Tuple[int, int, int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    if not boundsValues:
        return None
    return (
        min(bounds[0] for bounds in boundsValues),
        min(bounds[1] for bounds in boundsValues),
        max(bounds[2] for bounds in boundsValues),
        max(bounds[3] for bounds in boundsValues),
    )


def BuildOcrRegionCrop(
    imageBytes: bytes,
    textRegions: Sequence[ProductOcrTextRegion],
    anchorLabels: Sequence[str],
) -> Optional[Tuple[bytes, Tuple[int, int, int, int]]]:
    """지정한 상품정보 anchor를 포함하는 VLM 입력 영역을 자른다."""

    compactLabels = tuple(
        NormalizeWhiteSpace(label).lower().replace(" ", "")
        for label in anchorLabels
        if NormalizeWhiteSpace(label)
    )
    anchorRegions = [
        region
        for region in textRegions
        if any(
            label in NormalizeWhiteSpace(region.text).lower().replace(" ", "")
            for label in compactLabels
        )
    ]
    if len(anchorRegions) < 2:
        return None

    image = _DecodeImageBytes(imageBytes)
    imageHeight, imageWidth = image.shape[:2]
    anchorTop = min(region.bounds[1] for region in anchorRegions)
    anchorBottom = max(region.bounds[3] for region in anchorRegions)
    anchorLeft = min(region.bounds[0] for region in anchorRegions)
    verticalPadding = max(64, (anchorBottom - anchorTop) // 4)
    horizontalPadding = max(32, imageWidth // 40)
    top = max(0, anchorTop - verticalPadding)
    bottom = min(imageHeight, anchorBottom + verticalPadding)
    nearbyRegions = [
        region
        for region in textRegions
        if top <= (region.bounds[1] + region.bounds[3]) // 2 <= bottom
        and region.bounds[2] >= anchorLeft - horizontalPadding
    ]
    if not nearbyRegions:
        return None

    left = max(
        0,
        min(anchorLeft, *(region.bounds[0] for region in nearbyRegions))
        - horizontalPadding,
    )
    right = min(
        imageWidth,
        max(region.bounds[2] for region in nearbyRegions) + horizontalPadding,
    )
    if right - left < 128 or bottom - top < 128:
        return None
    if (right - left) * (bottom - top) >= imageWidth * imageHeight * 0.90:
        return None
    return _EncodeImageBytes(image[top:bottom, left:right], ".png"), (
        left,
        top,
        right,
        bottom,
    )


def _DecodeImageBytes(imageBytes: bytes) -> object:
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise ProductOcrError(
            "OCR image decoding requires numpy and cv2."
        ) from error
    imageArray = np.frombuffer(imageBytes, dtype=np.uint8)
    image = cv2.imdecode(imageArray, cv2.IMREAD_COLOR)
    if image is None:
        raise ProductOcrError("failed to decode image bytes for OCR.")
    return image


def _ReadBox(value: object) -> Optional[Tuple[float, float, float, float]]:
    try:
        import numpy as np

        coordinates = np.asarray(value, dtype=float).reshape(-1)
    except Exception:
        return None
    if coordinates.size < 4 or coordinates.size % 2 != 0:
        return None
    xValues = coordinates[0::2]
    yValues = coordinates[1::2]
    return (
        float(xValues.min()),
        float(yValues.min()),
        float(xValues.max()),
        float(yValues.max()),
    )


def _EncodeImageBytes(image: object, suffix: str = ".jpg") -> bytes:
    try:
        import cv2
    except ImportError as error:
        raise ProductOcrError("OCR image encoding requires cv2.") from error
    normalizedSuffix = suffix if suffix.startswith(".") else ".jpg"
    success, encodedImage = cv2.imencode(normalizedSuffix, image)
    if not success:
        raise ProductOcrError("failed to encode OCR tile image.")
    return bytes(encodedImage)
