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


class HsCodeClassificationPipeline:
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
        for component in (
            EvidenceIntakeComponent(context.rawInput),
            ProductUnderstandingComponent(),
            Hs2RoutingComponent(),
            ClassificationComponent(),
        ):
            context.ExecuteComponent(component)
            if context.shouldStop:
                return
