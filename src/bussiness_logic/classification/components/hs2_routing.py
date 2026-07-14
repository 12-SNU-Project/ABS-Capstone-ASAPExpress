"""Route product understanding into HS2 classification scope."""

from __future__ import annotations

from bussiness_logic.pipeline.component_base import BasePipelineComponent
from bussiness_logic.pipeline.blackboard import BlackboardStore, now_iso
from bussiness_logic.pipeline.model.schema import JsonValue, Hs2RoutingDecision
from bussiness_logic.classification.repositories.chapter_index_repository import LoadPreClassificationChapterRows
from bussiness_logic.classification.services.pre_classification_router import (
    BuildPreClassificationRouteInput,
    PreClassificationDomainRouter,
)


class Hs2RoutingComponent(BasePipelineComponent):
    component_name = "HS2_Routing_Component"
    stage = "Regulatory_Domain_Routing"
    llm_model = None

    def Run(self, store: BlackboardStore) -> None:
        bb = store.load()
        productUnderstanding = bb.get("product_understanding") or {}
        if not isinstance(productUnderstanding, dict):
            raise RuntimeError("No ProductUnderstandingPackage on the Blackboard.")
        understandingId = str(productUnderstanding.get("understanding_id") or "")
        productId = str(productUnderstanding.get("product_id") or "")
        self.ReadBlackBoard(understandingId)

        identityLane = productUnderstanding.get("identity_hints") or {}
        if not isinstance(identityLane, dict):
            identityLane = {}
        distilledIdentity = productUnderstanding.get("distilled_identity") or {}
        if not isinstance(distilledIdentity, dict):
            distilledIdentity = {}
        identityTerms = self._StringTuple(identityLane.get("identity_terms") or [])
        productFormTerms = self._StringTuple(identityLane.get("product_form_terms") or [])
        distilledFormTerms = self._StringTuple(
            distilledIdentity.get("product_form_signal_terms") or [],
        )
        distilledProcessingTerms = self._StringTuple(
            distilledIdentity.get("processing_signal_terms") or [],
        )
        domainHints = self._StringTuple(identityLane.get("domain_hints") or [])
        chapterHints = self._StringTuple(
            identityLane.get("chapter_hint_terms") or [],
        )
        chapterHintSources = self._StringTuple(
            identityLane.get("chapter_hint_source_terms") or [],
        )
        compositionFacts = productUnderstanding.get("composition_facts") or {}
        if not isinstance(compositionFacts, dict):
            compositionFacts = {}
        routeInput = BuildPreClassificationRouteInput(
            productName=str(productUnderstanding.get("product_name") or ""),
            shortDescription="",
            factTexts=(
                str(identityLane.get("commercial_identity") or ""),
                str(identityLane.get("translated_product_name") or ""),
                str(identityLane.get("normalized_tariff_description") or ""),
                *identityTerms,
                *productFormTerms,
                *distilledFormTerms,
                *distilledProcessingTerms,
                *domainHints,
                *chapterHints,
                *chapterHintSources,
            ),
            structuredProductFacts=[],
            processingState=str(identityLane.get("processing_state") or ""),
            containsSauceOrBroth=(
                bool(compositionFacts.get("contains_sauce_or_broth"))
                if "contains_sauce_or_broth" in compositionFacts else None
            ),
        )
        routeHint = PreClassificationDomainRouter(
            chapterRowsProvider=LoadPreClassificationChapterRows,
        ).Route(routeInput)
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
    def _StringTuple(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value.strip(),) if value.strip() else ()
        if not isinstance(value, list):
            return ()
        return tuple(str(item).strip() for item in value if str(item).strip())

    @staticmethod
    def _TraceDict(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return dict(value)
