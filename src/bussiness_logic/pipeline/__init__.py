"""Pipeline orchestration public API."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "BuildRawInputFromPreparedFacts": "bussiness_logic.pipeline.export_requirement_pipeline",
    "BuildKurlyUrlFactsFromPipelineResult": "bussiness_logic.pipeline.export_requirement_pipeline",
    "BuildRawInputFromUi": "bussiness_logic.pipeline.export_requirement_pipeline",
    "CollectKurlyProductFactsIfNeeded": "bussiness_logic.pipeline.export_requirement_pipeline",
    "CollectKurlyUrlFacts": "bussiness_logic.pipeline.export_requirement_pipeline",
    "ExportRequirementPipeline": "bussiness_logic.pipeline.export_requirement_pipeline",
    "LoadCachedProductInputFacts": "bussiness_logic.pipeline.export_requirement_pipeline",
    "PIPELINE_OUTPUTS_ROOT": "bussiness_logic.pipeline.export_requirement_pipeline",
    "PrepareUserInputFacts": "bussiness_logic.pipeline.export_requirement_pipeline",
    "PRODUCT_INPUT_ARTIFACT_ROOT": "bussiness_logic.pipeline.export_requirement_pipeline",
    "RerunCachedInputReconstruction": "bussiness_logic.pipeline.export_requirement_pipeline",
    "RunExportRequirementPipeline": "bussiness_logic.pipeline.export_requirement_pipeline",
    "ExportPipelineManager": "bussiness_logic.pipeline.pipeline_manager",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    if name not in _EXPORT_MODULES:
        raise AttributeError(name)
    value = getattr(import_module(_EXPORT_MODULES[name]), name)
    globals()[name] = value
    return value
