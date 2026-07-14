from bussiness_logic.classification.services.pre_classification_router import (
    PreClassificationDomainRouter,
    PreClassificationRouteInput,
)
from bussiness_logic.legacy.core.classification.hierarchical_beam import (
    HIERARCHY_LEVEL_HS2,
    HierarchySearchBoundary,
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
    assert routeHint.ToTrace()["allowed_hs2"] == ["19"]


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


def test_router_uses_chapter_index_guardrail_for_prepared_seafood(monkeypatch) -> None:
    # Legacy (pre-bucket) contract: guardrail hard-blocks the raw chapter.
    monkeypatch.setenv("ASAP_HS2_BUCKET_SCOPE", "0")
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


def test_router_bucket_scope_keeps_guardrailed_chapter(monkeypatch) -> None:
    # Bucket mode (default): the redirect bonus stays as ranking pressure but
    # the raw chapter keeps its own evidence and the whole domain bucket joins
    # the allowed boundary — a usage-text "cooked" word must not erase the
    # answer chapter (organic pepper lost ch07 to ch20 this way).
    monkeypatch.setenv("ASAP_HS2_BUCKET_SCOPE", "1")
    routeInput = PreClassificationRouteInput(
        productName="유기농 고추",
        shortDescription="organic pepper",
        factTexts=("frozen vegetables", "요리나 소스에 활용",),
    )
    router = PreClassificationDomainRouter(
        chapterRowsProvider=lambda: (
            {
                "chapter": "07",
                "chapter_keywords": "vegetables; pepper",
                "raw_scope_signals": "frozen; fresh",
                "prepared_food_redirect_chapters": "20",
                "routing_guardrails": "route prepared products before raw ingredient chapter",
                "domain_scope_candidates": "food",
            },
            {
                "chapter": "20",
                "chapter_keywords": "preserved vegetables; jam",
                "domain_scope_candidates": "food",
            },
            {
                "chapter": "33",
                "chapter_keywords": "perfume; cosmetic",
                "domain_scope_candidates": "cosmetics",
            },
        ),
    )

    routeHint = router.Route(routeInput)

    assert "07" in routeHint.candidateHs2
    assert "33" not in routeHint.candidateHs2  # other bucket stays out
    assert routeHint.blockedHs2 == ()
    assert routeHint.routingBasis.method == "cn_chapter_index_bucket_scope"
    scores = {d["chapter"]: d["score"] for d in routeHint.candidateChapterDetails}
    assert scores.get("07", 0) > 0  # score-through, not just recall


def test_router_condiment_product_form_can_rank_over_seafood_ingredient(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ASAP_HS2_BUCKET_SCOPE", "1")
    routeInput = PreClassificationRouteInput(
        productName="[연안식당] 부추 꼬막 비빔장",
        shortDescription="",
        factTexts=(
            "prepared sauce seasoned with cockle",
            "원재료명: 새꼬막살, 부추, 혼합간장, 소스",
        ),
    )
    router = PreClassificationDomainRouter(
        chapterRowsProvider=lambda: (
            {
                "chapter": "16",
                "chapter_keywords": (
                    "meat fish; fish crustaceans; molluscs aquatic; "
                    "aquatic invertebrates; prepared"
                ),
                "prepared_scope_signals": "prepared; sauce; seasoned",
                "domain_scope_candidates": "food; animal_origin",
            },
            {
                "chapter": "21",
                "chapter_keywords": "prepared; preparations; sauce",
                "domain_scope_candidates": "food",
            },
        ),
    )

    routeHint = router.Route(routeInput)

    assert routeHint.candidateHs2[0] == "21"
    details = {d["chapter"]: d for d in routeHint.candidateChapterDetails}
    assert details["21"]["score"] > details["16"]["score"]
    assert "condiment_product_form_bonus" in details["21"]["matched_terms"]
    assert details["21"]["score_breakdown"]["product_form_bonus"] > 0


def test_router_plain_seafood_dish_does_not_get_condiment_bonus(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ASAP_HS2_BUCKET_SCOPE", "1")
    routeInput = PreClassificationRouteInput(
        productName="[압구정낙지] 낙지 볶음 500g",
        shortDescription="",
        factTexts=(
            "prepared stir-fried octopus",
            "원재료명: 낙지, 소스, 고춧가루",
        ),
    )
    router = PreClassificationDomainRouter(
        chapterRowsProvider=lambda: (
            {
                "chapter": "16",
                "chapter_keywords": "molluscs aquatic; prepared seafood",
                "prepared_scope_signals": "prepared; sauce",
                "domain_scope_candidates": "food; animal_origin",
            },
            {
                "chapter": "21",
                "chapter_keywords": "prepared; sauce",
                "domain_scope_candidates": "food",
            },
        ),
    )

    routeHint = router.Route(routeInput)

    assert routeHint.candidateHs2[0] == "16"
    details = {d["chapter"]: d for d in routeHint.candidateChapterDetails}
    assert "condiment_product_form_bonus" not in details["21"]["matched_terms"]


def test_routing_context_builds_hs2_hard_boundary() -> None:
    boundary = HierarchySearchBoundary(
        allowedCodesByLevel={HIERARCHY_LEVEL_HS2: frozenset({"19"})},
        excludedCodesByLevel={HIERARCHY_LEVEL_HS2: frozenset({"03"})},
    )

    assert boundary.Allows(HIERARCHY_LEVEL_HS2, "19")
    assert not boundary.Allows(HIERARCHY_LEVEL_HS2, "21")
    assert not boundary.Allows(HIERARCHY_LEVEL_HS2, "03")
