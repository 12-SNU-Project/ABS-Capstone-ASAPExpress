"""OCR fallback, OCR engine, and OCR fact normalization."""

from bussiness_logic.product.ocr.ocr_fallback import (
    ProductOcrArtifactStore,
    ProductOcrFallbackRunner,
    ProductOcrImageDownloader,
    ProductOcrImageResult,
    ProductOcrTextQualityEvaluator,
)
from bussiness_logic.product.ocr.ocr_normalization import (
    ProductOcrFactNormalizationResult,
    ProductOcrFactNormalizer,
)
from bussiness_logic.product.ocr.ocr_image_tiling import (
    ProductOcrImageTile,
    ProductOcrImageTilePlan,
    ProductOcrImageTilePlanner,
)
from bussiness_logic.product.ocr.paddle_ocr import (
    PaddleOcrEngine,
    ProductOcrEngine,
    ProductOcrError,
    ProductOcrTableCandidate,
    ProductOcrTableResult,
    ProductOcrTileTextResult,
    ProductStructuredOcrResult,
    ProductStructuredOcrEngine,
    ProductTableLayoutDiagnostic,
    ProductTableLayoutRegion,
    ProductTableRecognitionEvidence,
)
from bussiness_logic.product.ocr.vlm_adapter import (
    BridgeVlmAdapter,
    BuildProductVlmAdapter,
    VlmTableBlock,
    VlmTableExtraction,
    VlmTableRow,
)

__all__ = [
    "PaddleOcrEngine",
    "ProductOcrEngine",
    "ProductOcrError",
    "ProductOcrTableCandidate",
    "ProductOcrTableResult",
    "ProductOcrTileTextResult",
    "ProductStructuredOcrResult",
    "ProductStructuredOcrEngine",
    "ProductTableLayoutDiagnostic",
    "ProductTableLayoutRegion",
    "ProductTableRecognitionEvidence",
    "BridgeVlmAdapter",
    "BuildProductVlmAdapter",
    "VlmTableBlock",
    "VlmTableExtraction",
    "VlmTableRow",
    "ProductOcrFactNormalizationResult",
    "ProductOcrFactNormalizer",
    "ProductOcrImageTile",
    "ProductOcrImageTilePlan",
    "ProductOcrImageTilePlanner",
    "ProductOcrArtifactStore",
    "ProductOcrFallbackRunner",
    "ProductOcrImageDownloader",
    "ProductOcrImageResult",
    "ProductOcrTextQualityEvaluator",
]
