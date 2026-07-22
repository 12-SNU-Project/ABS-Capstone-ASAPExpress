"""Structured table VLM adapters used by ProductStructuredOcrEngine."""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

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


class VlmTableBlock(BaseModel):
    """VLM이 이미지에서 직접 관측한 단일 표."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    html: str
    bounds: Optional[Tuple[float, float, float, float]] = None


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
        imageBytes, imageWidth, imageHeight = self._EncodeImage(image)
        response = self._runtimeAdapter.Generate(
            LlmRequest(
                systemPrompt=(
                    "You extract table evidence from product-label images. "
                    "Copy only visible text and values. Never infer missing cells. "
                    "Return one JSON object matching the requested schema."
                ),
                userPrompt=(
                    "Extract every visible table. Preserve row and column relations "
                    "as minimal HTML table markup. bounds must be [left, top, right, "
                    "bottom] pixel coordinates relative to this image. Put other "
                    "visible text in raw_text. Return empty fields when not visible. "
                    "Use exactly this shape: {\"raw_text\":\"\",\"tables\":["
                    "{\"html\":\"<table>...</table>\",\"bounds\":[0,0,1,1]}]}."
                ),
                imageInputs=[
                    LlmImageInput(
                        mediaType="image/jpeg",
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
            bounds = table.bounds
            boundsInferred = bounds is None
            if bounds is None:
                bounds = (0.0, 0.0, float(imageWidth), float(imageHeight))
            tableBlocks.append(
                {
                    "block_label": "table",
                    "block_content": table.html,
                    "block_bbox": list(bounds),
                    "source_name": sourceName,
                    "bounds_inferred": boundsInferred,
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

    def _EncodeImage(self, image: object) -> tuple[bytes, int, int]:
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("opencv-python is required for VLM image encoding.") from error
        shape = getattr(image, "shape", None)
        if not isinstance(shape, tuple) or len(shape) < 2:
            raise ValueError("VLM adapter requires a decoded image array.")
        encoded, buffer = cv2.imencode(".jpg", image)
        if not encoded:
            raise ValueError("VLM input image could not be encoded as JPEG.")
        return bytes(buffer), int(shape[1]), int(shape[0])

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
