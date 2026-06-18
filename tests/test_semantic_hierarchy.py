from bussiness_logic.bridge import (
    TextEmbeddingProviderKind,
    TextEmbeddingRequest,
    TextEmbeddingResponse,
)
from bussiness_logic.core.context_retrieval.semantic_retrieval import (
    CnSemanticCandidateIndex,
)


class KeywordEmbeddingAdapter:
    def EmbedTexts(
        self,
        request: TextEmbeddingRequest,
    ) -> TextEmbeddingResponse:
        embeddings = [
            [1.0, 0.0]
            if "noodle" in text.lower() or "pasta" in text.lower()
            else [0.0, 1.0]
            for text in request.texts
        ]
        return TextEmbeddingResponse(
            provider=TextEmbeddingProviderKind.SENTENCE_TRANSFORMERS,
            modelName="keyword-fixture",
            embeddings=embeddings,
        )


def test_semantic_index_builds_parent_scoped_hierarchy_hints() -> None:
    rows = [
        {
            "chapter": "19",
            "chapter_description": "Preparations of cereals",
            "heading": "1902",
            "heading_description": "Pasta",
            "heading_keywords": "pasta; noodles",
            "subheading": "190219",
            "subheading_description": "Other uncooked pasta",
            "cn": "19021910",
            "cn_description": "Containing no common wheat flour",
        },
        {
            "chapter": "19",
            "chapter_description": "Preparations of cereals",
            "heading": "1905",
            "heading_description": "Bread and bakers' wares",
            "heading_keywords": "bread; bakery",
            "subheading": "190590",
            "subheading_description": "Other",
            "cn": "19059080",
            "cn_description": "Other",
        },
    ]
    semanticIndex = CnSemanticCandidateIndex(KeywordEmbeddingAdapter())
    semanticIndex.Build({"food": rows})

    hints = semanticIndex.SearchHierarchyHints(
        queryText="instant noodle",
        domainScopes=["food"],
        topKPerParent=1,
    )

    assert hints[("food", "hs2", "")][0].candidateCode == "19"
    assert hints[("food", "hs4", "19")][0].candidateCode == "1902"
    assert hints[("food", "hs6", "1902")][0].candidateCode == "190219"
    assert hints[("food", "cn8", "190219")][0].candidateCode == "19021910"


def test_leaf_search_keeps_existing_cn8_only_contract() -> None:
    row = {
        "chapter": "19",
        "heading": "1902",
        "heading_description": "Pasta",
        "heading_keywords": "pasta; noodles",
        "subheading": "190219",
        "cn": "19021910",
        "cn_description": "Noodles",
    }
    semanticIndex = CnSemanticCandidateIndex(KeywordEmbeddingAdapter())
    semanticIndex.Build({"food": [row]})

    hits = semanticIndex.Search(
        queryText="noodle",
        domainScopes=["food"],
        topK=5,
    )

    assert [hit.candidateCode for hit in hits] == ["19021910"]
    assert hits[0].matchedChunks[0].chunkId.startswith("19021910:")
    chunkPayload = semanticIndex.indexedChunks[0].model_dump(
        mode="json",
        by_alias=True,
    )
    assert "hierarchy_level" not in chunkPayload
    assert "parent_code" not in chunkPayload
