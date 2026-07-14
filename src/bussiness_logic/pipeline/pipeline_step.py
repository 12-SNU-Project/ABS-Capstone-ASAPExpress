"""Small wrapper for named pipeline execution steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bussiness_logic.pipeline.component_base import BasePipelineComponent
from bussiness_logic.pipeline.pipeline_context import PipelineContext


class RunnableStep(Protocol):
    def Run(self, context: PipelineContext) -> None:
        """Run one pipeline step."""


@dataclass(frozen=True)
class PipelineStep:
    stepName: str
    runner: RunnableStep | BasePipelineComponent

    def Run(self, context: PipelineContext) -> None:
        runnerType = (
            "component"
            if isinstance(self.runner, BasePipelineComponent)
            else "pipeline"
        )
        runnerName = (
            self.runner.component_name
            if isinstance(self.runner, BasePipelineComponent)
            else type(self.runner).__name__
        )
        stepResult = context.StartStep(
            stepName=self.stepName,
            runnerName=runnerName,
            runnerType=runnerType,
        )
        if isinstance(self.runner, BasePipelineComponent):
            componentResult = context.ExecuteComponent(self.runner)
            context.FinishStep(
                stepResult,
                status="completed" if componentResult.success else "failed",
                error=componentResult.error,
                outputsWritten=componentResult.outputs_written,
            )
            return
        try:
            self.runner.Run(context)
        except Exception as exc:
            context.FinishStep(
                stepResult,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        context.FinishStep(
            stepResult,
            status="stopped" if context.shouldStop else "completed",
        )
