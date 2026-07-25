"""Score-free DTOs for semantic HS2 chapter routing."""

from __future__ import annotations

from dataclasses import dataclass, field

from bussiness_logic.utils.json_types import JsonValue


@dataclass(frozen=True, slots=True)
class SemanticChapterRoutingBasis:
    method: str
    blockedReason: str = ""
    sourceTable: str = ""
    rowCount: int = 0

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "method": self.method,
            "blocked_reason": self.blockedReason,
            "source_table": self.sourceTable,
            "row_count": self.rowCount,
        }


@dataclass(frozen=True, slots=True)
class SemanticChapterRouteHint:
    candidateHs2: tuple[str, ...] = ()
    blockedHs2: tuple[str, ...] = ()
    domainScopes: tuple[str, ...] = ()
    preGateDomains: tuple[str, ...] = ()
    routingBasis: SemanticChapterRoutingBasis = SemanticChapterRoutingBasis(
        method="no_route_hint",
    )
    missingFacts: tuple[str, ...] = ()
    candidateChapterDetails: tuple[dict[str, JsonValue], ...] = ()
    selectedHs2: str = ""
    alternativeHs2: tuple[str, ...] = ()
    semanticDecision: dict[str, JsonValue] = field(default_factory=dict)

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "allowed_hs2": list(self.candidateHs2),
            "blocked_hs2": list(self.blockedHs2),
            "domain_scopes": list(self.domainScopes),
            "pre_gate_domains": list(self.preGateDomains),
            "routing_basis": self.routingBasis.ToTrace(),
            "missing_facts": list(self.missingFacts),
            "candidate_chapter_details": list(self.candidateChapterDetails),
            "selected_hs2": self.selectedHs2,
            "alternative_hs2": list(self.alternativeHs2),
            "semantic_decision": dict(self.semanticDecision),
        }
