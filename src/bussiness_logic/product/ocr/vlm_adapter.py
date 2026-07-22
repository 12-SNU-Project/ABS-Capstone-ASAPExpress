"""Structured table VLM adapters used by ProductStructuredOcrEngine."""

from __future__ import annotations

import json
import re
from html import escape
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from bussiness_logic.app_config import LlmProfileName
from bussiness_logic.bridge.adapter import RuntimeAdapter
from bussiness_logic.bridge.runtime_adapter import BuildPipelineRuntimeAdapter
from bussiness_logic.bridge.schema import (
    LlmGenerationOptions,
    LlmImageInput,
    LlmRequest,
    LlmResponseFormat,
)


class VlmTableRow(BaseModel):
    """VLM이 표에서 직접 전사한 단일 key/value 행."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    key: str = ""
    values: List[str] = Field(default_factory=list)
    sourceText: str = Field(default="", alias="source_text")


class VlmTableBlock(BaseModel):
    """VLM이 이미지에서 직접 관측한 단일 표."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    tableName: str = Field(default="", alias="table_name")
    rows: List[VlmTableRow] = Field(default_factory=list)


class VlmTableExtraction(BaseModel):
    """provider 독립 구조 표 추출 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    rawText: str = Field(default="", alias="raw_text")
    tables: List[VlmTableBlock] = Field(default_factory=list)


class BridgeVlmAdapter:
    """RuntimeAdapter vision 응답을 structured OCR block 계약으로 변환한다."""

    def __init__(self, runtimeAdapter: RuntimeAdapter[object]) -> None:
        self._runtimeAdapter = runtimeAdapter

    def predict(self, image: object) -> list[dict[str, object]]:
        imageBytes = self._EncodeImage(image)
        response = self._runtimeAdapter.Generate(
            LlmRequest(
                systemPrompt=(
                    "You extract table evidence from product-label images. "
                    "Copy only visible text and values. Never infer missing cells. "
                    "Return one JSON object matching the requested schema."
                ),
                userPrompt=(
                    "Extract every visible table as ordered rows. Copy text exactly; "
                    "do not normalize, correct, infer, or merge values. Each row must "
                    "contain key, ordered values, and source_text copied from the "
                    "visible row. Put visible non-table text in raw_text. Return empty "
                    "fields when not visible."
                ),
                imageInputs=[
                    LlmImageInput(
                        mediaType="image/png",
                        imageBytes=imageBytes,
                        sourceRef="product_ocr_tile",
                    )
                ],
                responseFormat=LlmResponseFormat.JSON_SCHEMA,
                responseSchemaName="vlm_table_extraction",
                responseSchema=VlmTableExtraction.model_json_schema(by_alias=True),
                responseModel=VlmTableExtraction,
                generationOptions=LlmGenerationOptions(
                    temperature=0,
                    maxTokens=4096,
                ),
            )
        )
        extraction = VlmTableExtraction.model_validate(
            self._ReadJsonObject(response.generatedText)
        )
        sourceName = self._BuildSourceName()
        tableBlocks = []
        for table in extraction.tables:
            if not table.rows:
                continue
            tableBlocks.append(
                {
                    "block_label": "table",
                    "block_content": self._BuildTableHtml(table),
                    "block_bbox": None,
                    "source_name": sourceName,
                    "table_name": table.tableName,
                    "source_rows": [row.sourceText for row in table.rows],
                }
            )
        return [
            {
                "res": {
                    "parsing_res_list": tableBlocks,
                    "bridge_raw_text": extraction.rawText,
                }
            }
        ]

    def _BuildSourceName(self) -> str:
        runtimeConfig = self._runtimeAdapter.RuntimeConfig()
        return "{0}:{1}".format(
            runtimeConfig.runtimeKind.value,
            runtimeConfig.modelName or "default",
        )

    def _BuildTableHtml(self, table: VlmTableBlock) -> str:
        rows = []
        for row in table.rows:
            cells = "".join(
                "<td>{0}</td>".format(escape(value))
                for value in row.values
            )
            rows.append(
                "<tr><th>{0}</th>{1}</tr>".format(
                    escape(row.key),
                    cells or "<td></td>",
                )
            )
        return "<table>{0}</table>".format("".join(rows))

    def _EncodeImage(self, image: object) -> bytes:
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("opencv-python is required for VLM image encoding.") from error
        shape = getattr(image, "shape", None)
        if not isinstance(shape, tuple) or len(shape) < 2:
            raise ValueError("VLM adapter requires a decoded image array.")
        encoded, buffer = cv2.imencode(".png", image)
        if not encoded:
            raise ValueError("VLM input image could not be encoded as PNG.")
        return bytes(buffer)

    def _ReadJsonObject(self, text: str) -> dict[str, object]:
        rawText = str(text or "").strip()
        rawText = re.sub(r"^```(?:json)?", "", rawText).rstrip("`").strip()
        startIndex = rawText.find("{")
        endIndex = rawText.rfind("}")
        if startIndex < 0 or endIndex <= startIndex:
            raise ValueError("VLM response did not contain a JSON object.")
        parsed = json.loads(rawText[startIndex : endIndex + 1])
        if not isinstance(parsed, dict):
            raise ValueError("VLM response JSON must be an object.")
        return parsed


def BuildProductVlmAdapter(providerName: str) -> Optional[object]:
    """Build the configured VLM adapter; PaddleOCR-VL needs no injected adapter."""

    normalizedProviderName = providerName.strip().lower()
    if normalizedProviderName == "paddleocr_vl":
        return None
    if normalizedProviderName == "llm_bridge":
        return BridgeVlmAdapter(
            BuildPipelineRuntimeAdapter(LlmProfileName.PRODUCT_VLM)
        )
    raise ValueError(
        "structured_ocr_provider must be paddleocr_vl or llm_bridge."
    )
