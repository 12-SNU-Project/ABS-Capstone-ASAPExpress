"""Collect Kurly product facts when a supported product URL is present."""

from __future__ import annotations

from bussiness_logic.pipeline.export_requirement_pipeline import (
    CollectKurlyProductFactsIfNeeded,
)
from bussiness_logic.pipeline.pipeline_context import PipelineContext


class KurlyProductCollectionPipeline:
    def Run(self, context: PipelineContext) -> None:
        context.Emit(
            "Kurly_Product_Collection",
            "running",
            message="Kurly 상품 정보 수집 확인",
        )
        previousFacts = dict(context.facts)
        context.facts = CollectKurlyProductFactsIfNeeded(facts=context.facts)
        changed = context.facts != previousFacts
        context.Emit(
            "Kurly_Product_Collection",
            "completed" if changed else "skipped",
            message=(
                "Kurly 상품 정보 수집 완료"
                if changed
                else "수집 대상 Kurly URL 없음"
            ),
        )
