"""Route product understanding into HS2 classification scope."""

from __future__ import annotations

from bussiness_logic.pipeline.component_base import BasePipelineComponent
from bussiness_logic.pipeline.blackboard import BlackboardStore, now_iso
from bussiness_logic.classification.model.hs2_routing import Hs2RoutingDecision
from bussiness_logic.classification.repositories.chapter_index_repository import LoadPreClassificationChapterRows
from bussiness_logic.classification.services.semantic_chapter_router import SemanticChapterRouter
from bussiness_logic.utils.json_types import JsonValue


class Hs2RoutingComponent(BasePipelineComponent):
    component_name = "HS2_Routing_Component"
    stage = "Regulatory_Domain_Routing"
    llm_model = None

    def __init__(self, runtimeAdapter: object | None = None) -> None:
        self._runtimeAdapter = runtimeAdapter

    def Run(self, store: BlackboardStore) -> None:
        bb = store.load()
        productUnderstanding = bb.get("product_understanding") or {}
        if not isinstance(productUnderstanding, dict):
            raise RuntimeError("No ProductUnderstandingPackage on the Blackboard.")
        understandingId = str(productUnderstanding.get("understanding_id") or "")
        productId = str(productUnderstanding.get("product_id") or "")
        self.ReadBlackBoard(understandingId)

        routeHint = SemanticChapterRouter(
            chapterRowsProvider=LoadPreClassificationChapterRows,
            runtimeAdapter=self._runtimeAdapter,
        ).Route(productUnderstanding)
        routingDecisionId = store.next_id("route")
        routingContext = Hs2RoutingDecision(
            routingDecisionId=routingDecisionId,
            productId=productId,
            sourceUnderstandingId=understandingId,
            allowedHs2=routeHint.candidateHs2,
            blockedHs2=routeHint.blockedHs2,
            enforceHs2Boundary=bool(routeHint.candidateHs2),
            fallbackAllowed=True,
            domainScopes=routeHint.domainScopes,
            preGateDomains=routeHint.preGateDomains,
            routingBasis=self._TraceDict(routeHint.routingBasis.ToTrace()),
            missingFacts=routeHint.missingFacts,
            candidateChapterDetails=routeHint.candidateChapterDetails,
            selectedHs2=routeHint.selectedHs2,
            alternativeHs2=routeHint.alternativeHs2,
            semanticDecision=routeHint.semanticDecision,
        )
        store.put(
            "routing_context",
            routingContext.ToBlackboard(
                createdBy=self.component_name,
                createdAt=now_iso(),
            ),
        )
        self.WriteBlackBoard(routingDecisionId)
        self.reason(
            "Hs2RoutingDecision 생성: "
            f"allowed_hs2={list(routeHint.candidateHs2)}, "
            f"fallback_allowed={routingContext.fallbackAllowed}."
        )

    @staticmethod
    def _TraceDict(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return dict(value)
