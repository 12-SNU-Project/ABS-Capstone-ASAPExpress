"""Route product understanding into HS2 classification scope."""

from __future__ import annotations

from agents.agent_base import BaseAgent
from agents.blackboard import BlackboardStore, now_iso
from agents.pipeline_dto import JsonValue, RoutingContext
from agents.tools.pre_classification_router import (
    BuildPreClassificationRouteInput,
    PreClassificationDomainRouter,
)


class DomainRouterAgent(BaseAgent):
    agent_name = "Domain_Router_Agent"
    stage = "Regulatory_Domain_Routing"
    llm_model = None

    def run(self, store: BlackboardStore) -> None:
        bb = store.load()
        productUnderstanding = bb.get("product_understanding") or {}
        if not isinstance(productUnderstanding, dict):
            raise RuntimeError("No ProductUnderstandingFacts on the Blackboard.")
        understandingId = str(productUnderstanding.get("understanding_id") or "")
        productId = str(productUnderstanding.get("product_id") or "")
        self.read_input(understandingId)

        factTexts = self._StringTuple(
            productUnderstanding.get("classification_input_fact_texts") or [],
        )
        routingTerms = self._StringTuple(
            productUnderstanding.get("routing_terms") or [],
        )
        productFacts = productUnderstanding.get("classification_input_product_facts")
        structuredFacts = self._FactDictList(productFacts)
        routeInput = BuildPreClassificationRouteInput(
            productName=str(productUnderstanding.get("product_name") or ""),
            shortDescription=str(productUnderstanding.get("short_description") or ""),
            factTexts=(*factTexts, *routingTerms),
            structuredProductFacts=structuredFacts,
        )
        routeHint = PreClassificationDomainRouter().Route(routeInput)
        routingContextId = store.next_id("route")
        routingContext = RoutingContext(
            routingContextId=routingContextId,
            productId=productId,
            sourceUnderstandingId=understandingId,
            candidateHs2=routeHint.candidateHs2,
            blockedHs2=routeHint.blockedHs2,
            strictRoute=bool(routeHint.candidateHs2),
            fallbackAllowed=True,
            domainScopes=routeHint.domainScopes,
            preGateDomains=routeHint.preGateDomains,
            routingBasis=self._TraceDict(routeHint.routingBasis.ToTrace()),
            missingFacts=routeHint.missingFacts,
        )
        store.put(
            "routing_context",
            routingContext.ToBlackboard(
                createdBy=self.agent_name,
                createdAt=now_iso(),
            ),
        )
        self.wrote(routingContextId)
        self.reason(
            "RoutingContext 생성: "
            f"candidate_hs2={list(routeHint.candidateHs2)}, "
            f"fallback_allowed={routingContext.fallbackAllowed}."
        )

    @staticmethod
    def _StringTuple(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value.strip(),) if value.strip() else ()
        if not isinstance(value, list):
            return ()
        return tuple(str(item).strip() for item in value if str(item).strip())

    @staticmethod
    def _FactDictList(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        facts: list[dict[str, object]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            facts.append({
                str(key): factValue
                for key, factValue in item.items()
                if isinstance(key, str)
            })
        return facts

    @staticmethod
    def _TraceDict(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return dict(value)
