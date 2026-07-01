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


def test_router_uses_chapter_index_rows_for_raw_seafood_hs2() -> None:
    routeInput = PreClassificationRouteInput(
        productName="이유식용 국산 다진 대구살 90g",
        shortDescription="frozen minced Korean cod fish",
        factTexts=("원산지: 국산",),
    )
    router = PreClassificationDomainRouter(
        chapterRowsProvider=lambda: (
            {
                "chapter": "03",
                "chapter_keywords": "fish; seafood; cod",
                "raw_scope_signals": "cod; fish",
                "domain_scope_candidates": "food; animal_origin",
            },
            {
                "chapter": "21",
                "chapter_keywords": "soup; sauce",
                "domain_scope_candidates": "food",
            },
        ),
    )

    routeHint = router.Route(routeInput)

    assert routeHint.candidateHs2[0] == "03"
    assert routeHint.domainScopes == ("food", "animal_origin")
    assert routeHint.preGateDomains == ("animal_origin",)
    assert routeHint.routingBasis.sourceTable == "cn_chapter_index"


def test_router_uses_chapter_index_guardrail_for_prepared_seafood() -> None:
    routeInput = PreClassificationRouteInput(
        productName="낙지 볶음 500g",
        shortDescription="stir-fried octopus",
        factTexts=("보관상태: 냉동",),
    )
    router = PreClassificationDomainRouter(
        chapterRowsProvider=lambda: (
            {
                "chapter": "03",
                "chapter_keywords": "fish; seafood; octopus",
                "raw_scope_signals": "octopus",
                "prepared_food_redirect_chapters": "16",
                "routing_guardrails": "route prepared products before raw ingredient chapter",
                "domain_scope_candidates": "food; animal_origin",
            },
            {
                "chapter": "16",
                "chapter_keywords": "prepared fish; prepared seafood",
                "domain_scope_candidates": "food; animal_origin",
            },
        ),
    )

    routeHint = router.Route(routeInput)

    assert routeHint.candidateHs2[0] == "16"
    assert routeHint.blockedHs2 == ("03",)
    assert routeHint.routingBasis.method == "cn_chapter_index_keyword_guardrail"


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
