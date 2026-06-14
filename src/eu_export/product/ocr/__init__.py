"""OCR fallback, OCR engine, and OCR fact normalization."""

from eu_export.product.ocr.ocr_fallback import (
    ProductOcrArtifactStore,
    ProductOcrFallbackRunner,
    ProductOcrImageDownloader,
    ProductOcrImageResult,
    ProductOcrTextQualityEvaluator,
)
from eu_export.product.ocr.ocr_normalization import (
    ProductOcrFactNormalizationResult,
    ProductOcrFactNormalizer,
)
from eu_export.product.ocr.ocr_image_tiling import (
    ProductOcrImageTile,
    ProductOcrImageTilePlan,
    ProductOcrImageTilePlanner,
)
from eu_export.product.ocr.paddle_ocr import (
    PaddleOcrEngine,
    PaddleStructureOcrEngine,
    ProductOcrEngine,
    ProductOcrError,
    ProductOcrTableResult,
    ProductOcrTileTextResult,
    ProductStructuredOcrResult,
)

__all__ = [
    "PaddleOcrEngine",
    "PaddleStructureOcrEngine",
    "ProductOcrEngine",
    "ProductOcrError",
    "ProductOcrTableResult",
    "ProductOcrTileTextResult",
    "ProductStructuredOcrResult",
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
