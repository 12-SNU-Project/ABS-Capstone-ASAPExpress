"""상품 이미지 OCR adapter."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from eu_export.utils import NormalizeWhitespace


class ProductOcrError(RuntimeError):
    """OCR engine 초기화 또는 추론이 실패했을 때 사용한다."""


class ProductOcrEngine(ABC):
    """이미지 bytes에서 OCR 텍스트를 추출하는 adapter interface."""

    @abstractmethod
    def ExtractTextFromImage(self, imageBytes: bytes) -> str:
        raise NotImplementedError


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
        ocr = self._ReadInitializedOcr()

        if hasattr(ocr, "predict"):
            result = ocr.predict(image)
        elif hasattr(ocr, "ocr"):
            result = ocr.ocr(image, cls=self._useTextlineOrientation)
        else:
            raise ProductOcrError("PaddleOCR object does not expose predict or ocr.")

        return "\n".join(self._ExtractResultTexts(result))

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
        try:
            import cv2
            import numpy as np
        except ImportError as error:
            raise ProductOcrError(
                "PaddleOcrEngine requires numpy and cv2 to decode image bytes."
            ) from error

        imageArray = np.frombuffer(imageBytes, dtype=np.uint8)
        image = cv2.imdecode(imageArray, cv2.IMREAD_COLOR)
        if image is None:
            raise ProductOcrError("failed to decode image bytes for OCR.")

        return image

    def _ExtractResultTexts(self, result: Any) -> List[str]:
        texts: List[str] = []
        self._CollectTextValues(result, texts)
        return [NormalizeWhitespace(text) for text in texts if NormalizeWhitespace(text)]

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
