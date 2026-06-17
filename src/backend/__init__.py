"""Backend service boundary for UI-facing pipeline execution."""

from backend.pipeline_api import PipelineApi
from backend.pipeline_projection import PipelineRunResult
from backend.pipeline_service import (
    PipelineRunRequest,
    PipelineRunService,
    RunRegistry,
)

__all__ = [
    "PipelineApi",
    "PipelineRunRequest",
    "PipelineRunResult",
    "PipelineRunService",
    "RunRegistry",
]
