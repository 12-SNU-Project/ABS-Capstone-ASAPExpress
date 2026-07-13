"""Run product evidence intake and HS/CN classification components."""

from __future__ import annotations

from bussiness_logic.pipeline.components import (
    ClassificationComponent,
    EvidenceIntakeComponent,
    Hs2RoutingComponent,
    ProductUnderstandingComponent,
)
from bussiness_logic.pipeline.export_requirement_pipeline import (
    BuildRawInputFromPreparedFacts,
)
from bussiness_logic.pipeline.pipeline_context import PipelineContext
from bussiness_logic.pipeline.pipeline_step import PipelineStep


class _BuildClassificationRawInputStep:
    def Run(self, context: PipelineContext) -> None:
        context.Emit(
            "Input_Intake",
            "running",
            message="사용자 입력/URL/OCR evidence intake 준비",
        )
        context.rawInput = BuildRawInputFromPreparedFacts(
            query=context.query,
            facts=context.facts,
        )
        context.Emit(
            "Input_Intake",
            "completed",
            message="raw product facts 생성",
            raw_input=context.rawInput,
        )


class HsCodeClassificationPipeline:
    def Run(self, context: PipelineContext) -> None:
        PipelineStep(
            "build_raw_input",
            _BuildClassificationRawInputStep(),
        ).Run(context)
        if context.shouldStop:
            return
        for step in self._BuildComponentSteps(context):
            step.Run(context)
            if context.shouldStop:
                return

    def _BuildComponentSteps(
        self,
        context: PipelineContext,
    ) -> tuple[PipelineStep, ...]:
        return (
            PipelineStep(
                "evidence_intake",
                EvidenceIntakeComponent(context.rawInput),
            ),
            PipelineStep(
                "product_understanding",
                ProductUnderstandingComponent(),
            ),
            PipelineStep(
                "hs2_routing",
                Hs2RoutingComponent(),
            ),
            PipelineStep(
                "classification",
                ClassificationComponent(),
            ),
        )
