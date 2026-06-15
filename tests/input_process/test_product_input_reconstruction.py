import pytest

pytest.importorskip("rapidfuzz")

from eu_export.input_process.dictionary import (
    ProductDictionaryEntry,
    ProductDictionaryRetriever,
)
from eu_export.input_process.product_input_adapter import ProductInputAdapter
from eu_export.input_process.reconstruction import (
    ProductFactReconstructionResult,
    ProductInputReconstructionService,
)


def _BuildRetriever() -> ProductDictionaryRetriever:
    return ProductDictionaryRetriever(
        [
            ProductDictionaryEntry(
                term_id="nutrition_001",
                canonical_name="나트륨",
                term_type="nutrition_label",
                aliases=["나트류"],
                source_name="test",
                source_id="sodium",
            ),
            ProductDictionaryEntry(
                term_id="nutrition_002",
                canonical_name="탄수화물",
                term_type="nutrition_label",
                aliases=["탄수하물"],
                source_name="test",
                source_id="carbohydrate",
            ),
            ProductDictionaryEntry(
                term_id="ingredient_001",
                canonical_name="대두",
                term_type="ingredient",
                aliases=["콩"],
                source_name="test",
                source_id="soybean",
            ),
            ProductDictionaryEntry(
                term_id="nutrition_003",
                canonical_name="콜레스테롤",
                term_type="nutrition_label",
                aliases=[],
                source_name="test",
                source_id="cholesterol",
            ),
        ],
        fuzzyMinRatio=0.8,
        minFuzzyCharacters=4,
    )


def test_dictionary_retriever_uses_alias_and_fuzzy_match() -> None:
    retriever = _BuildRetriever()

    aliasMatches = retriever.FindMatchesForText("나트류")
    fuzzyMatches = retriever.FindMatchesForText("콜래스테롤")

    assert aliasMatches[0].canonicalName == "나트륨"
    assert aliasMatches[0].correctionAction == "auto_corrected"
    assert fuzzyMatches[0].canonicalName == "콜레스테롤"


def test_dictionary_retriever_does_not_fuzzy_correct_short_terms() -> None:
    retriever = _BuildRetriever()

    assert retriever.FindMatchesForText("대추") == []


def test_input_reconstruction_builds_normalized_facts_from_structured_ocr() -> None:
    service = ProductInputReconstructionService()
    collectionResult = {
        "product_page_url": "https://www.kurlyglobal.com/products/example",
        "parsed_product_page": {
            "product_notice_options": [
                {
                    "option_name": None,
                    "fields": [
                        {
                            "field_name": "제품명",
                            "field_value": "테스트 만두",
                        }
                    ],
                }
            ],
        },
    }
    ocrImageResults = [
        {
            "structured_ocr": {
                "tables": [
                    {
                        "plain_text": "영양성분 나트류 320mg 탄수하물 40g",
                    }
                ],
                "raw_tile_texts": [
                    {
                        "tile_index": 1,
                        "text": "원재료명: 밀가루, 대두",
                    }
                ],
            }
        }
    ]

    result = service.ReconstructFromPipelineParts(
        collectionResult=collectionResult,
        ocrImageResults=ocrImageResults,
        combinedOcrText="",
    )

    normalizedText = "\n".join(result.normalizedFactTexts)
    assert result.productFacts
    assert "제품명: 테스트 만두" in normalizedText
    assert "나트륨" in normalizedText
    assert "탄수화물" in normalizedText


def test_product_input_adapter_prefers_reconstruction_fact_texts() -> None:
    productInput = ProductInputAdapter().BuildFromData(
        {
            "parsed_product_page": {
                "product_name": "테스트 만두",
                "product_domain": "food",
            },
            "combined_ocr_text": "원재료명: 나트류",
            "ocr_normalization": {
                "fact_texts": ["원재료명: 나트류"],
            },
            "input_reconstruction": ProductFactReconstructionResult(
                normalized_fact_texts=["원재료명: 나트륨"],
            ).model_dump(mode="json", by_alias=True),
        }
    )

    assert productInput.normalizedOcrFactTexts == ["원재료명: 나트륨"]
