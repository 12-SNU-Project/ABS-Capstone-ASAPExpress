"""Backend service boundary for UI-facing pipeline execution."""

from backend.app import CreateBackendApp
from backend.pipeline_api import PipelineApi
from backend.pipeline_projection import PipelineRunResult
from backend.pipeline_service import (
    PipelineRunRequest,
    PipelineRunService,
    RunRegistry,
)

__all__ = [
    "CreateBackendApp",
    "PipelineApi",
    "PipelineRunRequest",
    "PipelineRunResult",
    "PipelineRunService",
    "RunRegistry",
]
