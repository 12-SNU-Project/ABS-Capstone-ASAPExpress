"""Prepare user-provided product facts before collection/classification."""

from __future__ import annotations

from bussiness_logic.input_process.product_facts import PrepareUserInputFacts
from bussiness_logic.pipeline.pipeline_context import PipelineContext


class UserInputPreparationPipeline:
    def Run(self, context: PipelineContext) -> None:
        context.Emit(
            "User_Input_Preparation",
            "running",
            message="사용자 입력 facts 정리",
        )
        context.facts = PrepareUserInputFacts(
            query=context.query,
            facts=context.facts,
        )
        context.Emit(
            "User_Input_Preparation",
            "completed",
            message="사용자 입력 facts 정리 완료",
        )
