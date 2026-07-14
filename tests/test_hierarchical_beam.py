from bussiness_logic.legacy.core.classification.hierarchical_beam import (
    CnHierarchyIndex,
    HierarchyBeamPath,
    HierarchyBeamSelector,
    HierarchyNodeScore,
)


def _Row(
    chapter: str,
    heading: str,
    subheading: str,
    cn: str,
    *,
    headingDescription: str = "",
    headingKeywords: str = "",
) -> dict[str, str]:
    return {
        "chapter": chapter,
        "heading": heading,
        "subheading": subheading,
        "cn": cn,
        "heading_description": headingDescription,
        "heading_keywords": headingKeywords,
    }


def test_index_deduplicates_parent_nodes() -> None:
    index = CnHierarchyIndex({
        "food": [
            _Row("19", "1902", "190220", "19022091"),
            _Row("19", "1902", "190220", "19022099"),
            _Row("21", "2104", "210410", "21041000"),
        ],
    })

    assert [node.code for node in index.GetChildren("food", "hs2")] == ["19", "21"]
    assert [node.code for node in index.GetChildren("food", "hs4", "19")] == ["1902"]
    assert [node.code for node in index.GetChildren("food", "hs6", "1902")] == [
        "190220",
    ]
    assert [node.code for node in index.GetChildren("food", "cn8", "190220")] == [
        "19022091",
        "19022099",
    ]


def test_index_aggregates_immediate_child_search_text() -> None:
    index = CnHierarchyIndex({
        "food": [
            _Row(
                "19",
                "1902",
                "190220",
                "19022091",
                headingDescription="Pasta, whether or not cooked",
                headingKeywords="pasta; noodles",
            ),
            _Row(
                "19",
                "1905",
                "190590",
                "19059080",
                headingDescription="Bread and other bakers' wares",
                headingKeywords="bread; bakery",
            ),
        ],
    })

    chapterNode = index.GetChildren("food", "hs2")[0]

    assert "Pasta, whether or not cooked" in chapterNode.childDescriptionText
    assert "Bread and other bakers' wares" in chapterNode.childDescriptionText
    assert "noodles" in chapterNode.childKeywordText
    assert "bakery" in chapterNode.childKeywordText


def test_hs6_child_keywords_exclude_repeated_branch_keywords() -> None:
    row = _Row("16", "1605", "160555", "16055500")
    row["cn_keywords"] = "octopus"
    row["branch_keywords"] = "aquatic invertebrates"
    index = CnHierarchyIndex({"food": [row]})

    hs6Node = index.GetChildren("food", "hs6", "1605")[0]

    assert hs6Node.childKeywordText == "octopus"
    assert "aquatic invertebrates" not in hs6Node.childKeywordText


def test_selector_reserves_semantic_recall_slot() -> None:
    index = CnHierarchyIndex({
        "food": [
            _Row("16", "1601", "160100", "16010010"),
            _Row("19", "1902", "190220", "19022091"),
            _Row("21", "2104", "210410", "21041000"),
        ],
    })
    nodes = index.GetChildren("food", "hs2")
    scores = [
        HierarchyNodeScore(node=nodes[0], score=9.0),
        HierarchyNodeScore(node=nodes[1], score=8.0),
        HierarchyNodeScore(node=nodes[2], score=1.0, semanticScore=0.9),
    ]

    selected = HierarchyBeamSelector().SelectForParent(
        HierarchyBeamPath(domainScope="food"),
        scores,
        limit=3,
        semanticCodes=["21"],
        semanticSlots=1,
    )

    assert [path.currentNode.node.code for path in selected] == ["16", "19", "21"]
    assert selected[-1].retrievalSources == ("heuristic", "semantic")


def test_selector_reserves_structural_residual_branch() -> None:
    index = CnHierarchyIndex({
        "food": [
            _Row("33", "3304", "330410", "33041000"),
            _Row("33", "3304", "330420", "33042000"),
            _Row("33", "3304", "330499", "33049900"),
        ],
    })
    nodes = index.GetChildren("food", "hs6", "3304")
    scores = [
        HierarchyNodeScore(node=nodes[0], score=9.0),
        HierarchyNodeScore(node=nodes[1], score=8.0),
        HierarchyNodeScore(node=nodes[2], score=0.0),
    ]

    selected = HierarchyBeamSelector().SelectForParent(
        HierarchyBeamPath(domainScope="food"),
        scores,
        limit=2,
        residualCodes=["330499"],
    )

    assert [path.currentNode.node.code for path in selected] == [
        "330410",
        "330499",
    ]


def test_global_pruning_uses_cumulative_score_then_evidence_counts() -> None:
    index = CnHierarchyIndex({
        "food": [
            _Row("16", "1601", "160100", "16010010"),
            _Row("19", "1902", "190220", "19022091"),
            _Row("21", "2104", "210410", "21041000"),
        ],
    })
    nodes = index.GetChildren("food", "hs2")
    paths = [
        HierarchyBeamPath(domainScope="food").Extend(
            HierarchyNodeScore(node=nodes[0], score=5.0),
        ),
        HierarchyBeamPath(domainScope="food").Extend(
            HierarchyNodeScore(
                node=nodes[1],
                score=5.0,
                primaryMatches=("pasta",),
            ),
        ),
        HierarchyBeamPath(domainScope="food").Extend(
            HierarchyNodeScore(node=nodes[2], score=3.0),
        ),
    ]

    selected = HierarchyBeamSelector().PruneGlobal(paths, limit=2)

    assert [path.currentNode.node.code for path in selected] == ["19", "16"]
