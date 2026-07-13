"""Small wrapper for named pipeline execution steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bussiness_logic.pipeline.pipeline_context import PipelineContext


class RunnablePipeline(Protocol):
    def Run(self, context: PipelineContext) -> None:
        """Run one pipeline step."""


@dataclass(frozen=True)
class PipelineStep:
    stepName: str
    pipeline: RunnablePipeline

    def Run(self, context: PipelineContext) -> None:
        self.pipeline.Run(context)
