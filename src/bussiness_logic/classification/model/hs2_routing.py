"""HS2 routing pipeline models."""

from __future__ import annotations

from dataclasses import dataclass, field

from bussiness_logic.utils.json_types import JsonValue


def _desc(text: str) -> dict[str, str]:
    return {"description": text}


@dataclass(frozen=True, slots=True)
class Hs2RoutingDecision:
    routingDecisionId: str = field(metadata=_desc("HS2 라우팅 결정 ID"))
    productId: str = field(metadata=_desc("대상 상품 ID"))
    sourceUnderstandingId: str = field(metadata=_desc("원천 ProductUnderstandingPackage ID"))
    allowedHs2: tuple[str, ...] = field(metadata=_desc("허용 HS2 후보"))
    blockedHs2: tuple[str, ...] = field(metadata=_desc("차단 HS2 후보"))
    enforceHs2Boundary: bool = field(metadata=_desc("HS2 후보 범위 강제 여부"))
    fallbackAllowed: bool = field(metadata=_desc("후보 없음/실패 시 fallback 허용 여부"))
    domainScopes: tuple[str, ...] = field(metadata=_desc("도메인 scope 힌트"))
    preGateDomains: tuple[str, ...] = field(metadata=_desc("사전 게이트 도메인"))
    routingBasis: dict[str, JsonValue] = field(metadata=_desc("라우팅 판단 근거"))
    candidateChapterDetails: tuple[dict[str, JsonValue], ...] = field(
        default=(),
        metadata=_desc("HS2 후보별 점수와 매칭 근거"),
    )
    missingFacts: tuple[str, ...] = field(default=(), metadata=_desc("라우팅에 부족한 fact"))

    def ToBlackboard(self, *, createdBy: str, createdAt: str) -> dict[str, JsonValue]:
        return {
            "object_type": "Hs2RoutingDecision",
            "created_by": createdBy,
            "created_at": createdAt,
            "routing_decision_id": self.routingDecisionId,
            "product_id": self.productId,
            "source_understanding_id": self.sourceUnderstandingId,
            "allowed_hs2": list(self.allowedHs2),
            "blocked_hs2": list(self.blockedHs2),
            "enforce_hs2_boundary": self.enforceHs2Boundary,
            "fallback_allowed": self.fallbackAllowed,
            "domain_scopes": list(self.domainScopes),
            "pre_gate_domains": list(self.preGateDomains),
            "routing_basis": dict(self.routingBasis),
            "candidate_chapter_details": list(self.candidateChapterDetails),
            "missing_facts": list(self.missingFacts),
        }
