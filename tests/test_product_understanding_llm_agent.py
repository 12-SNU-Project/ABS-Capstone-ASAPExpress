from pytest import MonkeyPatch

from agents.llm_agents import identity_hint_agent
from agents.pipeline_components import product_understanding
from agents.pipeline_dto import (
    CoiEvidenceSet,
    DistilledIdentityFacts,
    EncyclopediaEvidenceSet,
    IdentityHintSet,
)


class FakeLlmResponse:
    generatedText: str = """{
      "translated_product_name": "stir-fried octopus",
      "commercial_identity": "Nakji-bokkeum",
      "normalized_tariff_description": "prepared stir-fried octopus",
      "identity_terms": ["octopus"],
      "product_form_terms": ["prepared seafood"],
      "domain_hints": ["food", "animal_origin"],
      "chapter_hint_terms": ["prepared seafood"],
      "chapter_hint_source_terms": ["octopus"],
      "chapter_hint_basis": "from_chapter_context",
      "chapter_hint_status": "enabled",
      "confidence": 0.9,
      "needs_review": false
    }"""


class FakeRuntimeAdapter:
    def Generate(self, request: object) -> FakeLlmResponse:
        del request
        return FakeLlmResponse()


class FakeIdentityHintAgent:
    calls: int = 0

    def BuildIdentityFacts(
        self,
        *,
        productName: str,
        distilledIdentity: DistilledIdentityFacts,
        encyclopediaEvidence: EncyclopediaEvidenceSet,
        factTexts: tuple[str, ...] = (),
    ) -> dict[str, object]:
        del productName, distilledIdentity, encyclopediaEvidence, factTexts
        type(self).calls += 1
        return {
            "understanding_mode": "llm_json",
            "product_form_terms": ("prepared seafood",),
            "domain_hints": ("food", "animal_origin"),
            "chapter_hint_terms": ("prepared fish",),
            "chapter_hint_source_terms": ("fish",),
            "chapter_hint_basis": "from_chapter_context",
            "chapter_hint_status": "enabled",
            "translated_product_name": "prepared seafood sauce",
            "confidence": 0.8,
            "needs_review": False,
            "commercial_identity": "prepared seafood",
            "normalized_tariff_description": "prepared seafood sauce",
            "identity_terms": ("seafood",),
        }


def _BuildSeedIdentity() -> IdentityHintSet:
    return IdentityHintSet(
        identityHintId="hint_001",
        productId="prod_001",
        commercialIdentity="주꾸미 볶음",
    )


def _BuildDistilledIdentity() -> DistilledIdentityFacts:
    return DistilledIdentityFacts(
        distilledIdentityId="distid_001",
        productId="prod_001",
        sourceEncyclopediaEvidenceId="ency_001",
        commercialIdentity="octopus",
        normalizedDescription="octopus prepared seafood",
        identityTerms=("octopus", "prepared", "seafood"),
        productFormSignalTerms=("seafood",),
        processingSignalTerms=("prepared",),
    )


def test_identity_hint_agent_runs_by_default(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("ASAP_USE_LLM_UNDERSTANDING", raising=False)
    FakeIdentityHintAgent.calls = 0
    monkeypatch.setattr(
        product_understanding,
        "IdentityHintAgent",
        FakeIdentityHintAgent,
    )

    identity = product_understanding.ProductUnderstandingComponent._MaybeEnrichIdentityWithLlm(
        _BuildSeedIdentity(),
        productName="주꾸미 볶음",
        distilledIdentity=_BuildDistilledIdentity(),
        encyclopediaEvidence=EncyclopediaEvidenceSet(
            encyclopediaEvidenceId="ency_001",
            productId="prod_001",
            query="주꾸미 볶음",
            configured=True,
        ),
    )

    assert FakeIdentityHintAgent.calls == 1
    assert identity.understandingMode == "llm_json"
    assert identity.chapterHintTerms == ("prepared fish",)
    assert identity.translatedProductName == "prepared seafood sauce"
    assert identity.compositionTerms == ()


def test_identity_hint_agent_does_not_reference_missing_short_description(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity_hint_agent, "_adapter_cache", [FakeRuntimeAdapter()])
    monkeypatch.setattr(identity_hint_agent, "_chapter_context", lambda: "")

    result = identity_hint_agent.IdentityHintAgent().BuildIdentityFacts(
        productName="낙지볶음",
        distilledIdentity=_BuildDistilledIdentity(),
        encyclopediaEvidence=EncyclopediaEvidenceSet(
            encyclopediaEvidenceId="ency_001",
            productId="prod_001",
            query="낙지볶음",
            configured=True,
        ),
    )

    assert result["understanding_mode"] == "llm_json"
    assert result["translated_product_name"] == "stir-fried octopus"
    assert result["chapter_hint_terms"] == ("prepared seafood",)


def test_identity_hint_agent_can_be_disabled(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("ASAP_USE_LLM_UNDERSTANDING", "0")
    FakeIdentityHintAgent.calls = 0
    monkeypatch.setattr(
        product_understanding,
        "IdentityHintAgent",
        FakeIdentityHintAgent,
    )
    seedIdentity = _BuildSeedIdentity()

    identity = product_understanding.ProductUnderstandingComponent._MaybeEnrichIdentityWithLlm(
        seedIdentity,
        productName="주꾸미 볶음",
        distilledIdentity=_BuildDistilledIdentity(),
        encyclopediaEvidence=EncyclopediaEvidenceSet(
            encyclopediaEvidenceId="ency_001",
            productId="prod_001",
            query="주꾸미 볶음",
            configured=True,
        ),
    )

    assert FakeIdentityHintAgent.calls == 0
    assert identity is seedIdentity


def test_composition_lane_ignores_nested_subingredient_percentage() -> None:
    composition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명",
                "normalized_value": (
                    "곡류가공품[밀가루(밀:호주산), "
                    "옥수수전분(옥수수100%)], 당면"
                ),
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )

    assert composition.ingredientPercentages == ()
    assert composition.principalIngredient == ""
    assert "ingredient_percentages" in composition.missingCompositionFacts


def test_composition_lane_keeps_top_level_ingredient_percentages() -> None:
    composition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명",
                "normalized_value": "돼지고기 25%, 밀가루 20%, 소스",
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )

    assert list(composition.ingredientPercentages) == [
        {"term": "돼지고기", "percent": 25.0},
        {
            "term": "밀가루",
            "percent": 20.0,
            "term_aliases": ["wheat flour", "flour", "wheat"],
        },
    ]
    assert "meat" in composition.ingredientClasses
    assert "cereal" in composition.ingredientClasses
    assert "seasoning_sauce" in composition.ingredientClasses
    assert composition.principalIngredient == "돼지고기"
    assert composition.principalIngredientStatus == "confirmed"
    assert composition.principalIngredientCandidates[0]["ingredient_name"] == "돼지고기"
    assert composition.missingCompositionFacts == ()


def test_composition_lane_does_not_promote_component_percentage_to_principal() -> None:
    composition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명 (카덴 우동면)",
                "normalized_value": "밀가루(밀:호주산, 미국산), 정제소금",
            },
            {
                "field_name": "원재료명 (가쓰오팩)",
                "normalized_value": "가다랑어 100%(인도네시아산)",
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )

    assert list(composition.ingredientPercentages) == [
        {"term": "가다랑어", "percent": 100.0},
    ]
    assert composition.principalIngredient == ""
    assert composition.principalIngredientStatus == "unknown"
    assert composition.principalIngredientCandidates[0]["ingredient_name"] == "가다랑어"
    assert composition.principalIngredientCandidates[0]["scope"] == "component"
    assert composition.principalIngredientCandidates[0]["component_name"] == "가쓰오팩"
    katsuoEntries = [
        entry
        for entry in composition.ingredientEntries
        if entry["ingredient_name"] == "가다랑어"
    ]
    assert katsuoEntries[0]["scope"] == "component"
    assert katsuoEntries[0]["component_name"] == "가쓰오팩"
    assert {
        component["component_name"]
        for component in composition.componentCompositions
    } == {"가쓰오팩", "카덴 우동면"}
    assert composition.missingCompositionFacts == ()


def test_composition_lane_uses_reconstructed_tables_for_component_weights() -> None:
    composition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명 (카덴 우동면)",
                "normalized_value": "밀가루, 정제소금",
                "source_refs": ["evidence-10"],
            },
        ),
        reconstructedTables=(
            {
                "table_name": "제품 구성 정보",
                "source_refs": ["evidence-20"],
                "rows": [
                    {
                        "field_name": "카덴 우동면 내용량",
                        "normalized_value": "180",
                        "unit": "g",
                        "source_refs": ["evidence-20"],
                    }
                ],
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )

    assert composition.ingredientEntries[0]["ingredient_name"] == "밀가루"
    assert composition.componentCompositions[0]["content_weight"] == 180
    assert composition.componentCompositions[0]["content_weight_unit"] == "g"


def test_composition_lane_keeps_minor_percent_out_of_confirmed_principal() -> None:
    composition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명",
                "normalized_value": (
                    "연육[외국산/어육살], 변성전분, 대파 6%(국산), "
                    "양파 6%(국산)"
                ),
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )

    assert composition.principalIngredient == ""
    assert composition.principalIngredientStatus == "ambiguous"
    assert composition.principalIngredientCandidates[0]["ingredient_name"] == "연육"
    assert list(composition.ingredientPercentages) == [
        {"term": "대파", "percent": 6.0},
        {"term": "양파", "percent": 6.0},
    ]


def test_composition_lane_parses_percent_after_origin_parentheses() -> None:
    composition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명",
                "normalized_value": (
                    "찹쌀(국내산) 70.75 %, "
                    "서리태(검정콩/국내산) 20.28 %, 정백당"
                ),
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )

    assert list(composition.ingredientPercentages) == [
        {
            "term": "찹쌀",
            "percent": 70.75,
            "term_aliases": ["glutinous rice", "rice"],
        },
        {
            "term": "서리태",
            "percent": 20.28,
            "term_aliases": ["black soybean", "soybean", "bean"],
        },
    ]
    assert "cereal" in composition.ingredientClasses
    assert "soy_legume" in composition.ingredientClasses
    assert composition.principalIngredient == "찹쌀"
    assert composition.principalIngredientStatus == "confirmed"
    assert composition.compositionBasis == "label"


def test_composition_lane_keeps_nested_origin_percentages_out() -> None:
    composition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명",
                "normalized_value": "마늘(국산 50%, 중국산 50%), 소스",
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )

    assert composition.ingredientPercentages == ()
    assert composition.principalIngredient == ""
    assert composition.principalIngredientStatus == "ambiguous"


def test_composition_lane_excludes_nutrition_from_component_projection() -> None:
    composition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명",
                "normalized_value": "낙지(베트남산), 소스",
            },
            {
                "field_name": "내용량",
                "normalized_value": "500g",
            },
        ),
        reconstructedTables=(
            {
                "table_name": "영양정보",
                "rows": [
                    {"field_name": "단백질", "normalized_value": "36", "unit": "g"},
                    {"field_name": "당류", "normalized_value": "47", "unit": "g"},
                ],
            },
            {
                "table_name": "제품 정보",
                "rows": [
                    {"field_name": "제품명", "normalized_value": "압구정낙지볶음"},
                    {"field_name": "원재료명", "normalized_value": "낙지, 소스"},
                ],
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )

    componentNames = {
        str(component.get("component_name") or "")
        for component in composition.componentCompositions
    }
    assert "단백질" not in componentNames
    assert "당류" not in componentNames
    assert "내용량" not in componentNames
    assert all("영양정보" not in term for term in composition.compositionTerms)
    assert all("제품명" not in term for term in composition.compositionTerms)
    assert list(composition.compositionTerms) == [
        "원재료명: 낙지(베트남산), 소스",
        "제품 정보 / 원재료명: 낙지, 소스",
    ]


def test_composition_lane_projects_label_processing_state_and_classes() -> None:
    composition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "식품유형",
                "normalized_value": "기타 수산물가공품(가열하여 섭취하는 냉동식품)",
            },
            {
                "field_name": "원재료명",
                "normalized_value": "재첩국물(국산) 86%, 재첩살(국산) 12%, 천일염(국산) 2%",
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )

    assert composition.processingState == "frozen cooked prepared"
    assert "mollusc" in composition.ingredientClasses
    assert "seasoning_sauce" not in composition.ingredientClasses
    assert list(composition.ingredientPercentages) == [
        {
            "term": "재첩국물",
            "percent": 86.0,
            "term_aliases": ["clam", "corbicula", "mollusc"],
        },
        {
            "term": "재첩살",
            "percent": 12.0,
            "term_aliases": ["clam", "corbicula", "mollusc"],
        },
        {"term": "천일염", "percent": 2.0},
    ]


def test_composition_lane_wrapper_detection_avoids_single_character_noise() -> None:
    starchComposition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명",
                "normalized_value": "타피오카전분, 파프리카, 소스",
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_001",
            productId="prod_001",
        ),
    )
    dumplingComposition = product_understanding.ProductUnderstandingComponent._BuildCompositionLane(
        factTexts=(),
        productFacts=(
            {
                "field_name": "원재료명",
                "normalized_value": "만두피[밀가루], 돼지고기",
            },
        ),
        coiEvidence=CoiEvidenceSet(
            coiEvidenceId="coi_002",
            productId="prod_002",
        ),
    )

    assert starchComposition.containsWrapperOrDough is False
    assert dumplingComposition.containsWrapperOrDough is True
