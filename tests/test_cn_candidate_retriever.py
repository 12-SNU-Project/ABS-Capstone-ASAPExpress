from pathlib import Path

from bussiness_logic.core.classification.hierarchical_beam import (
    HierarchyBeamConfig,
)
from bussiness_logic.core.classification.stage1 import (
    CnCandidateRetriever,
    ProductClassificationInput,
)
from bussiness_logic.core.context_retrieval.semantic_retrieval import (
    CnSemanticCandidateIndex,
    CnSemanticSearchHit,
)


def _Product(productName: str) -> ProductClassificationInput:
    return ProductClassificationInput(
        productName=productName,
        shortDescription="",
        productDomain="food",
        domainScopes=["food"],
    )


def _Row(
    chapter: str,
    heading: str,
    subheading: str,
    cn8: str,
    keyword: str,
) -> dict[str, str]:
    return {
        "chapter": chapter,
        "chapter_description": keyword,
        "chapter_keywords": keyword,
        "heading": heading,
        "heading_description": keyword,
        "heading_keywords": keyword,
        "subheading": subheading,
        "subheading_description": keyword,
        "subheading_keywords": keyword,
        "cn": cn8,
        "cn_description": keyword,
        "cn_keywords": keyword,
    }


def _Retriever(
    rows: list[dict[str, str]],
    config: HierarchyBeamConfig | None = None,
) -> CnCandidateRetriever:
    retriever = CnCandidateRetriever(
        ontologyRootPath=Path("."),
        projectRootPath=Path("."),
        beamConfig=config,
    )
    retriever._rowsByDomainScope = {"food": rows}
    return retriever


def test_hierarchical_score_is_sum_of_each_level_once() -> None:
    retriever = _Retriever([
        _Row("19", "1902", "190219", "19021910", "noodles"),
    ])

    candidates = retriever.FindCandidates(_Product("noodles"), topK=5)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert set(candidate.hierarchyLevelPoints) == {
        "hs2",
        "hs4",
        "hs6",
        "cn8",
    }
    assert candidate.score == sum(candidate.hierarchyLevelPoints.values())
    assert candidate.score > 0


def test_candidate_dto_aliases_and_prompt_contract_remain_compatible() -> None:
    retriever = _Retriever([
        _Row("19", "1902", "190219", "19021910", "noodles"),
    ])
    candidate = retriever.FindCandidates(_Product("noodles"), topK=1)[0]

    candidatePayload = candidate.model_dump(mode="json", by_alias=True)
    promptPayload = candidate.ToPromptDict()

    assert candidatePayload["domain_scope"] == "food"
    assert candidatePayload["code_hierarchy"]["hs6"]["code"] == "190219"
    assert "score_breakdown" in candidatePayload
    assert "hierarchy_level_points" not in candidatePayload
    assert "hard_condition_status" not in candidatePayload
    assert promptPayload["hs8"] == "19021910"
    assert promptPayload["hs6_code"] == "190219"
    assert "candidate_context_text" in promptPayload
    assert "classification_rule_texts" in promptPayload


def test_static_terms_match_basic_singular_plural_variants() -> None:
    retriever = _Retriever([
        _Row("18", "1803", "180310", "18031000", "cocoa paste"),
        _Row("21", "2103", "210390", "21039090", "sauces seasonings"),
    ])

    candidates = retriever.FindCandidates(
        _Product("fermented chili sauce seasoning"),
        topK=1,
    )

    assert candidates[0].hs4Code == "2103"


def test_url_only_input_does_not_surface_generic_candidates() -> None:
    retriever = _Retriever([
        _Row("19", "1902", "190220", "19022099", "products pasta"),
    ])
    productInput = ProductClassificationInput(
        productName="https://www.kurlyglobal.com/products/m00000056840?",
        shortDescription="Korean food, ramen, meal kits, and groceries.",
        productDomain="food",
        domainScopes=["food"],
    )

    assert retriever.FindCandidates(productInput, topK=5) == []


def test_low_value_meal_word_does_not_score_mustard_candidate() -> None:
    retriever = _Retriever([
        _Row("21", "2103", "210330", "21033010", "mustard flour meal"),
    ])

    assert retriever.FindCandidates(_Product("산채나물 비빔밥"), topK=5) == []


def test_unknown_hard_condition_does_not_promote_generic_include_match() -> None:
    plainPasta = _Row("19", "1902", "190219", "19021910", "pasta")
    cookedStuffed = _Row("19", "1902", "190220", "19022091", "pasta")
    cookedStuffed["include_rule_keywords"] = "pre-cooked pasta; pasta"
    cookedStuffed["hard_conditions"] = "cooked"
    retriever = _Retriever([plainPasta, cookedStuffed])

    candidates = retriever.FindCandidates(_Product("우동"), topK=5)

    assert candidates[0].hs8 == "19021910"
    assert all(
        candidate.includeRuleMatches == []
        for candidate in candidates
        if candidate.hs8 == "19022091"
    )


def test_preferred_heading_keeps_parent_hs2_in_beam() -> None:
    riceCandidate = _Row("19", "1905", "190590", "19059020", "rice")
    bibimbapCandidate = _Row("21", "2106", "210690", "21069098", "food")
    bibimbapCandidate["heading_keywords"] = "food"
    bibimbapCandidate["subheading_keywords"] = ""
    bibimbapCandidate["cn_keywords"] = "비빔밥"
    retriever = _Retriever([riceCandidate, bibimbapCandidate])

    candidates = retriever.FindCandidates(_Product("산채나물 비빔밥"), topK=1)

    assert candidates[0].hs8 == "21069098"


def test_quantitative_hard_condition_remains_unknown_without_structured_proof() -> None:
    row = _Row("21", "2103", "210390", "21039090", "salt sauce")
    row["hard_conditions"] = "at least 5 g/l of salt"
    retriever = _Retriever([row])

    candidate = retriever.FindCandidates(_Product("salt sauce"), topK=1)[0]

    assert candidate.hardConditionStatus == "unknown"
    assert candidate.hardConditionEvidence == ["at least 5 g/l of salt"]


class SemanticHintIndex(CnSemanticCandidateIndex):
    def __init__(self) -> None:
        pass

    def SearchHierarchyHints(
        self,
        queryText: str,
        domainScopes: list[str],
        topKPerParent: int,
        minScore: float = 0.0,
    ) -> dict[tuple[str, str, str], list[CnSemanticSearchHit]]:
        del queryText, domainScopes, topKPerParent, minScore
        return {
            ("food", "hs2", ""): [
                self._Hit("19", 0.99),
            ],
            ("food", "hs4", "19"): [
                self._Hit("1902", 0.98),
            ],
            ("food", "hs6", "1902"): [
                self._Hit("190219", 0.97),
            ],
            ("food", "cn8", "190219"): [
                self._Hit("19021910", 0.96),
            ],
        }

    def _Hit(self, code: str, score: float) -> CnSemanticSearchHit:
        return CnSemanticSearchHit(
            candidateCode=code,
            domainScope="food",
            score=score,
            bestChunkType="hierarchy",
            matchedChunks=[],
        )


def test_semantic_hint_uses_same_beam_without_adding_to_static_score() -> None:
    config = HierarchyBeamConfig(
        hs2PerParent=1,
        hs4PerParent=1,
        hs6PerParent=1,
        hs2GlobalLimit=1,
        hs4GlobalLimit=1,
        hs6GlobalLimit=1,
        semanticSlotsPerParent=1,
    )
    retriever = _Retriever(
        [
            _Row("16", "1601", "160100", "16010010", "meat"),
            _Row("19", "1902", "190219", "19021910", "pasta"),
        ],
        config,
    )

    candidates = retriever.FindCandidatesWithSemanticIndex(
        _Product("unmapped term"),
        SemanticHintIndex(),
        heuristicTopK=1,
        semanticTopK=1,
        finalCandidateLimit=1,
    )

    assert [candidate.hs8 for candidate in candidates] == ["19021910"]
    assert candidates[0].score == 0
    assert candidates[0].retrievalSources == ["heuristic", "semantic"]
