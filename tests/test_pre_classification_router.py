from agents._external_classifier import _BuildRoutingBoundary
from agents.tools.pre_classification_router import (
    PreClassificationDomainRouter,
    PreClassificationRouteInput,
)
from bussiness_logic.core.classification.hierarchical_beam import (
    HIERARCHY_LEVEL_HS2,
)


def test_router_builds_noodle_route_dto() -> None:
    routeInput = PreClassificationRouteInput(
        productName="유탕면 라면",
        shortDescription="",
        factTexts=("밀가루 면류 제품",),
    )

    routeHint = PreClassificationDomainRouter().Route(routeInput)

    assert routeHint.candidateHs2 == ("19",)
    assert routeHint.domainScopes == ("food",)
    assert routeHint.routingBasis.matchedTerms == ("유탕면",)
    assert routeHint.ToTrace()["candidate_hs2"] == ["19"]


def test_router_marks_processed_animal_route_without_hard_filtering() -> None:
    routeInput = PreClassificationRouteInput(
        productName="주꾸미 볶음",
        shortDescription="양념 조리 수산물",
        factTexts=(),
    )

    routeHint = PreClassificationDomainRouter().Route(routeInput)

    assert routeHint.candidateHs2 == ("16",)
    assert routeHint.blockedHs2 == ("03",)
    assert routeHint.preGateDomains == ("animal_origin",)
    assert routeHint.missingFacts == ("primary_ingredient_ratio",)


def test_routing_context_builds_hs2_hard_boundary() -> None:
    boundary = _BuildRoutingBoundary({
        "candidate_hs2": ["19"],
        "blocked_hs2": ["03"],
        "strict_route": True,
    })

    assert boundary is not None
    assert boundary.Allows(HIERARCHY_LEVEL_HS2, "19")
    assert not boundary.Allows(HIERARCHY_LEVEL_HS2, "21")
    assert not boundary.Allows(HIERARCHY_LEVEL_HS2, "03")
