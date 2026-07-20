"""Pipeline run path helpers."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from bussiness_logic.app_config import LoadAppConfig
from bussiness_logic.artifact_paths import (
    BuildSafeArtifactPathSegment,
    ExtractProductIdFromUrl,
)
from bussiness_logic.utils.json_types import JsonObject


PROJECT_ROOT = Path(
    os.environ.get("ASAP_PROJECT_ROOT", Path(__file__).resolve().parents[3])
).resolve()
APP_CONFIG = LoadAppConfig(PROJECT_ROOT)
PIPELINE_OUTPUTS_ROOT = APP_CONFIG.paths.ResolvePath(
    PROJECT_ROOT,
    APP_CONFIG.paths.pipeline_outputs_root,
)


def ResolveProductArtifactId(query: str, facts: JsonObject) -> str:
    explicitProductId = BuildSafeArtifactPathSegment(
        str(facts.get("product_id") or ""),
        fallback="",
    )
    if explicitProductId:
        return explicitProductId

    sourceUrl = str(facts.get("url") or "").strip()
    if not sourceUrl:
        sourceUrls = facts.get("source_urls") or []
        if isinstance(sourceUrls, list) and sourceUrls:
            sourceUrl = str(sourceUrls[0] or "").strip()
    productIdFromUrl = ExtractProductIdFromUrl(sourceUrl)
    if productIdFromUrl != "unknown":
        return productIdFromUrl

    fallbackSeed = str(facts.get("product_name") or query or "unknown")
    fallbackDigest = hashlib.sha256(fallbackSeed.encode("utf-8")).hexdigest()[:12]
    return f"manual-{fallbackDigest}"


def BuildInternalRunId(jobId: str) -> str:
    digestBytes = hashlib.sha256(jobId.encode("utf-8")).digest()[:8]
    return "run_{0:020d}".format(int.from_bytes(digestBytes, byteorder="big"))
