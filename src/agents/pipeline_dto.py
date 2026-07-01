"""Internal agent DTOs for product understanding and routing."""

from __future__ import annotations

from dataclasses import dataclass


JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class CoiEvidenceSet:
    coiEvidenceId: str
    productId: str
    matchedDocuments: tuple[str, ...] = ()
    matchedTexts: tuple[str, ...] = ()
    matchScores: tuple[int, ...] = ()
    error: str = ""

    def ToBlackboard(self, *, createdBy: str, createdAt: str) -> dict[str, JsonValue]:
        return {
            "object_type": "CoiEvidenceSet",
            "created_by": createdBy,
            "created_at": createdAt,
            "coi_evidence_id": self.coiEvidenceId,
            "product_id": self.productId,
            "matched_documents": list(self.matchedDocuments),
            "matched_texts": list(self.matchedTexts),
            "match_scores": list(self.matchScores),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class EncyclopediaEntryDto:
    title: str
    description: str
    link: str
    contentHash: str

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "title": self.title,
            "description": self.description,
            "link": self.link,
            "content_hash": self.contentHash,
        }


@dataclass(frozen=True, slots=True)
class EncyclopediaEvidenceSet:
    encyclopediaEvidenceId: str
    productId: str
    query: str
    configured: bool
    entries: tuple[EncyclopediaEntryDto, ...] = ()
    qualityStatus: str = "unconfigured"
    qualityReasons: tuple[str, ...] = ()
    error: str = ""

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "encyclopedia_evidence_id": self.encyclopediaEvidenceId,
            "product_id": self.productId,
            "query": self.query,
            "configured": self.configured,
            "entries": [entry.ToTrace() for entry in self.entries],
            "quality_status": self.qualityStatus,
            "quality_reasons": list(self.qualityReasons),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class DistilledIdentityFacts:
    distilledIdentityId: str
    productId: str
    commercialIdentity: str = ""
    ingredientClass: str = "other"
    foodForm: str = "other"
    processingState: str = "unknown"
    normalizedTariffDescription: str = ""
    identityTerms: tuple[str, ...] = ()
    compositionTerms: tuple[str, ...] = ()
    processingTerms: tuple[str, ...] = ()
    confidence: float = 0.0
    conflictReason: str = ""

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "distilled_identity_id": self.distilledIdentityId,
            "product_id": self.productId,
            "commercial_identity": self.commercialIdentity,
            "ingredient_class": self.ingredientClass,
            "food_form": self.foodForm,
            "processing_state": self.processingState,
            "normalized_tariff_description": self.normalizedTariffDescription,
            "identity_terms": list(self.identityTerms),
            "composition_terms": list(self.compositionTerms),
            "processing_terms": list(self.processingTerms),
            "confidence": self.confidence,
            "conflict_reason": self.conflictReason,
        }


@dataclass(frozen=True, slots=True)
class ProductUnderstandingFacts:
    understandingId: str
    productId: str
    sourceProductId: str
    productName: str
    shortDescription: str
    classificationText: str
    classificationInputFactTexts: tuple[str, ...]
    classificationInputProductFacts: tuple[dict[str, JsonValue], ...]
    identity: DistilledIdentityFacts
    coiEvidence: CoiEvidenceSet
    encyclopediaEvidence: EncyclopediaEvidenceSet
    routingTerms: tuple[str, ...]
    blockedRoutingTerms: tuple[str, ...] = ()
    excludedFromRoutingTerms: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()

    def ToBlackboard(self, *, createdBy: str, createdAt: str) -> dict[str, JsonValue]:
        return {
            "object_type": "ProductUnderstandingFacts",
            "created_by": createdBy,
            "created_at": createdAt,
            "understanding_id": self.understandingId,
            "product_id": self.productId,
            "source_product_id": self.sourceProductId,
            "product_name": self.productName,
            "short_description": self.shortDescription,
            "classification_text": self.classificationText,
            "classification_input_fact_texts": list(self.classificationInputFactTexts),
            "classification_input_product_facts": list(self.classificationInputProductFacts),
            "identity_lane": self.identity.ToTrace(),
            "coi_evidence": self.coiEvidence.ToBlackboard(
                createdBy=createdBy,
                createdAt=createdAt,
            ),
            "encyclopedia_evidence": self.encyclopediaEvidence.ToTrace(),
            "routing_terms": list(self.routingTerms),
            "blocked_routing_terms": list(self.blockedRoutingTerms),
            "excluded_from_routing_terms": list(self.excludedFromRoutingTerms),
            "unknowns": list(self.unknowns),
        }


@dataclass(frozen=True, slots=True)
class RoutingContext:
    routingContextId: str
    productId: str
    sourceUnderstandingId: str
    candidateHs2: tuple[str, ...]
    blockedHs2: tuple[str, ...]
    strictRoute: bool
    fallbackAllowed: bool
    domainScopes: tuple[str, ...]
    preGateDomains: tuple[str, ...]
    routingBasis: dict[str, JsonValue]
    missingFacts: tuple[str, ...] = ()

    def ToBlackboard(self, *, createdBy: str, createdAt: str) -> dict[str, JsonValue]:
        return {
            "object_type": "RoutingContext",
            "created_by": createdBy,
            "created_at": createdAt,
            "routing_context_id": self.routingContextId,
            "product_id": self.productId,
            "source_understanding_id": self.sourceUnderstandingId,
            "candidate_hs2": list(self.candidateHs2),
            "blocked_hs2": list(self.blockedHs2),
            "strict_route": self.strictRoute,
            "fallback_allowed": self.fallbackAllowed,
            "domain_scopes": list(self.domainScopes),
            "pre_gate_domains": list(self.preGateDomains),
            "routing_basis": dict(self.routingBasis),
            "missing_facts": list(self.missingFacts),
        }
