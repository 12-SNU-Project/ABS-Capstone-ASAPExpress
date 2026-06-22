"""상품 이미지 OCR adapter."""

from abc import ABC, abstractmethod
from html.parser import HTMLParser
from math import ceil, floor
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, computed_field

from bussiness_logic.product.ocr.ocr_image_tiling import (
    ProductOcrImageTile,
    ProductOcrImageTilePlanner,
)
from bussiness_logic.utils import NormalizeWhiteSpace


class ProductOcrError(RuntimeError):
    """OCR engine 초기화 또는 추론이 실패했을 때 사용한다."""


class ProductOcrTableResult(BaseModel):
    """구조 OCR에서 추출한 단일 표 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    tableIndex: int = Field(alias="table_index")
    sourceName: str = Field(default="structured_ocr", alias="source_name")
    pageIndex: Optional[int] = Field(default=None, alias="page_index")
    tileIndex: Optional[int] = Field(default=None, alias="tile_index")
    html: str = ""
    cellTexts: List[str] = Field(default_factory=list, alias="cell_texts")
    plainText: str = Field(default="", alias="plain_text")


class ProductOcrTileTextResult(BaseModel):
    """타일 단위 raw OCR 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    tileIndex: Optional[int] = Field(default=None, alias="tile_index")
    text: str = ""


class ProductStructuredOcrResult(BaseModel):
    """표 우선 OCR 결과와 fallback 상태를 함께 보존한다."""

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


class PaddleOcrEngine(ProductOcrEngine):
    """PaddleOCR 기반 OCR adapter."""

    def __init__(
        self,
        lang: str = "korean",
        device: Optional[str] = None,
        useDocOrientationClassify: bool = False,
        useDocUnwarping: bool = False,
        useTextlineOrientation: bool = False,
        extraOptions: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._lang = lang
        self._device = device
        self._useDocOrientationClassify = useDocOrientationClassify
        self._useDocUnwarping = useDocUnwarping
        self._useTextlineOrientation = useTextlineOrientation
        self._extraOptions = dict(extraOptions or {})
        self._ocr: Any = None
        self.Initialize()

    def Initialize(self) -> None:
        """PaddleOCR 모델을 생성 시점에 한 번만 초기화한다."""

        if self._ocr is not None:
            return

        self._ocr = self._CreateOcr()

    def IsInitialized(self) -> bool:
        return self._ocr is not None

    def ExtractTextFromImage(self, imageBytes: bytes) -> str:
        image = self._DecodeImageBytes(imageBytes)
        return self._ExtractTextFromDecodedImage(image)

    def _ExtractTextFromDecodedImage(self, image: Any) -> str:
        ocr = self._ReadInitializedOcr()

        if hasattr(ocr, "predict"):
            result = ocr.predict(image)
        elif hasattr(ocr, "ocr"):
            result = ocr.ocr(image, cls=self._useTextlineOrientation)
        else:
            raise ProductOcrError("PaddleOCR object does not expose predict or ocr.")

        return "\n".join(self._ExtractResultTexts(result))

    def _EncodeImageBytes(self, image: Any, suffix: str = ".jpg") -> bytes:
        return _EncodeImageBytes(image, suffix)

    def _ReadInitializedOcr(self) -> Any:
        if self._ocr is None:
            raise ProductOcrError("PaddleOCR engine is not initialized.")

        return self._ocr

    def _CreateOcr(self) -> Any:
        try:
            from paddleocr import PaddleOCR
        except ImportError as error:
            raise ProductOcrError(
                "paddleocr package is required for PaddleOcrEngine."
            ) from error

        return self._CreatePaddleOcr(PaddleOCR)

    def _CreatePaddleOcr(self, paddleOcrClass: Any) -> Any:
        options: Dict[str, Any] = {
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
            legacyOptions: Dict[str, Any] = {
                "lang": self._lang,
                "use_angle_cls": self._useTextlineOrientation,
                **self._extraOptions,
            }
            return paddleOcrClass(**legacyOptions)

    def _DecodeImageBytes(self, imageBytes: bytes) -> Any:
        return _DecodeImageBytes(imageBytes)

    def _ExtractResultTexts(self, result: Any) -> List[str]:
        texts: List[str] = []
        self._CollectTextValues(result, texts)
        return [NormalizeWhiteSpace(text) for text in texts if NormalizeWhiteSpace(text)]

    def _CollectTextValues(self, value: Any, texts: List[str]) -> None:
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
        value: Dict[str, Any],
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
        value: Any,
        texts: List[str],
    ) -> None:
        if self._LooksLegacyOcrLine(value):
            textValue = value[1][0]
            if isinstance(textValue, str):
                texts.append(textValue)
            return

        for item in value:
            self._CollectTextValues(item, texts)

    def _LooksLegacyOcrLine(self, value: Any) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[1], (list, tuple))
            and len(value[1]) >= 1
            and isinstance(value[1][0], str)
        )


class PaddleOcrVlEngine(ProductOcrEngine):
    """PaddleOCR-VL 표 이해 결과를 TableRecognitionV2로 검증한다."""

    def __init__(
        self,
        device: Optional[str] = None,
        useDocOrientationClassify: bool = False,
        useDocUnwarping: bool = False,
        vlExtraOptions: Optional[Dict[str, Any]] = None,
        tableExtraOptions: Optional[Dict[str, Any]] = None,
        useImageTiling: bool = True,
        useProjectionTiling: bool = True,
        maxTileHeightPixels: int = 2400,
        maxTileSidePixels: int = 4000,
        tileOverlapPixels: int = 240,
        allowHardCutFallback: bool = False,
        tableCropPaddingPixels: int = 24,
        vlPipeline: Any = None,
        tablePipeline: Any = None,
    ) -> None:
        self._device = device
        self._useDocOrientationClassify = useDocOrientationClassify
        self._useDocUnwarping = useDocUnwarping
        self._vlExtraOptions = dict(vlExtraOptions or {})
        self._tableExtraOptions = dict(tableExtraOptions or {})
        self._tableCropPaddingPixels = max(0, tableCropPaddingPixels)
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
        tablesWithBounds: List[
            Tuple[ProductOcrTableResult, Tuple[int, int, int, int]]
        ] = []
        for tile in tilePlan.tiles:
            try:
                rawText, tableBlocks = self._ExtractVlTile(tile)
            except Exception as error:
                warnings.append(
                    "paddleocr_vl_failed tile={0}: {1}".format(
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
                tableResult, originalBounds, validationWarning = (
                    self._BuildTableResultFromVlBlock(
                        tile,
                        tableBlock,
                        tableIndex=len(tablesWithBounds) + 1,
                    )
                )
                if validationWarning is not None:
                    warnings.append(validationWarning)
                if tableResult is None or originalBounds is None:
                    continue
                if self._IsDuplicateTable(
                    tablesWithBounds,
                    tableResult,
                    originalBounds,
                ):
                    continue
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
                warnings=warnings,
            )

        return self._BuildRawFallbackResult(
            rawText,
            rawTileTexts,
            fallbackReason=(
                "paddleocr_vl_failed"
                if successfulVlTileCount == 0
                else "no_table_detected"
            ),
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
        warnings: List[str],
    ) -> ProductStructuredOcrResult:
        return ProductStructuredOcrResult(
            text=rawText,
            rawText=rawText,
            textMergeMode="raw_only",
            rawTileTexts=rawTileTexts,
            fallbackReason=fallbackReason,
            warnings=list(warnings),
        )

    def _ReadInitializedVlPipeline(self) -> Any:
        if self._vlPipeline is not None:
            return self._vlPipeline

        try:
            from paddleocr import PaddleOCRVL
        except ImportError as error:
            raise ProductOcrError(
                "paddleocr package with PaddleOCRVL is required."
            ) from error

        options: Dict[str, Any] = {
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
    ) -> Tuple[str, List[Mapping[str, Any]]]:
        output = self._ReadInitializedVlPipeline().predict(tile.image)
        markdownTexts: List[str] = []
        tableBlocks: List[Mapping[str, Any]] = []
        blockTexts: List[str] = []
        for result in output:
            payload = self._ReadResultPayload(result)
            markdownText = self._ReadMarkdownText(result)
            if markdownText:
                markdownTexts.append(markdownText)
            for block in payload.get("parsing_res_list", []):
                if not isinstance(block, Mapping):
                    continue
                content = block.get("block_content")
                if isinstance(content, str) and content.strip():
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
        tableBlock: Mapping[str, Any],
        tableIndex: int,
    ) -> Tuple[
        Optional[ProductOcrTableResult],
        Optional[Tuple[int, int, int, int]],
        Optional[str],
    ]:
        vlHtml = tableBlock.get("block_content")
        if not isinstance(vlHtml, str) or not self._LooksLikeTableHtml(vlHtml):
            return None, None, (
                "paddleocr_vl_table_invalid tile={0} table={1}".format(
                    tile.tileIndex or 1,
                    tableIndex,
                )
            )
        cropResult = self._BuildTableCrop(tile, tableBlock.get("block_bbox"))
        if cropResult is None:
            return None, None, (
                "paddleocr_vl_table_bbox_invalid tile={0} table={1}".format(
                    tile.tileIndex or 1,
                    tableIndex,
                )
            )
        tableCrop, originalBounds = cropResult
        html = vlHtml
        cellTexts = self._ExtractTextsFromHtml(html)
        sourceName = "paddleocr_vl_v1_6"
        validationWarning: Optional[str] = None
        try:
            verifiedPayload = self._ReadVerifiedTablePayload(tableCrop)
            validationError = self._ValidateVerifiedTablePayload(
                verifiedPayload,
                tableCrop,
            )
            if validationError is None:
                html = str(verifiedPayload.get("pred_html") or html)
                cellTexts = self._ReadCellTexts(verifiedPayload) or cellTexts
                sourceName = "paddleocr_vl_v1_6+table_recognition_v2"
            else:
                validationWarning = self._BuildValidationWarning(
                    tile,
                    tableIndex,
                    validationError,
                )
        except Exception as error:
            validationWarning = self._BuildValidationWarning(
                tile,
                tableIndex,
                str(error),
            )
        return ProductOcrTableResult(
            tableIndex=tableIndex,
            sourceName=sourceName,
            tileIndex=tile.tileIndex,
            html=html,
            cellTexts=cellTexts,
            plainText=self._BuildPlainTextFromHtml(html, cellTexts),
        ), originalBounds, validationWarning

    def _BuildTableCrop(
        self,
        tile: ProductOcrImageTile,
        rawBounds: Any,
    ) -> Optional[Tuple[Any, Tuple[int, int, int, int]]]:
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

    def _ReadInitializedTablePipeline(self) -> Any:
        if self._tablePipeline is not None:
            return self._tablePipeline
        try:
            from paddleocr import TableRecognitionPipelineV2
        except ImportError as error:
            raise ProductOcrError(
                "paddleocr package with TableRecognitionPipelineV2 is required."
            ) from error
        options: Dict[str, Any] = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_layout_detection": False,
            "use_ocr_model": True,
            **self._tableExtraOptions,
        }
        if self._device is not None:
            options["device"] = self._device
        self._tablePipeline = TableRecognitionPipelineV2(**options)
        return self._tablePipeline

    def _ReadVerifiedTablePayload(self, tableCrop: Any) -> Mapping[str, Any]:
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
        payload: Mapping[str, Any],
        tableCrop: Any,
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

    def _ReadCellTexts(self, payload: Mapping[str, Any]) -> List[str]:
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

    def _ReadResultPayload(self, result: Any) -> Mapping[str, Any]:
        jsonPayload = getattr(result, "json", None)
        payload = jsonPayload if isinstance(jsonPayload, Mapping) else result
        if not isinstance(payload, Mapping):
            return {}
        nestedPayload = payload.get("res")
        return nestedPayload if isinstance(nestedPayload, Mapping) else payload

    def _ReadMarkdownText(self, result: Any) -> str:
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

    def _ReadBox(self, value: Any) -> Optional[Tuple[float, float, float, float]]:
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


PaddleStructureOcrEngine = PaddleOcrVlEngine


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


def _DecodeImageBytes(imageBytes: bytes) -> Any:
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


def _EncodeImageBytes(image: Any, suffix: str = ".jpg") -> bytes:
    try:
        import cv2
    except ImportError as error:
        raise ProductOcrError("OCR image encoding requires cv2.") from error
    normalizedSuffix = suffix if suffix.startswith(".") else ".jpg"
    success, encodedImage = cv2.imencode(normalizedSuffix, image)
    if not success:
        raise ProductOcrError("failed to encode OCR tile image.")
    return bytes(encodedImage)
