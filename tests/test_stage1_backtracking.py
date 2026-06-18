from pathlib import Path

from bussiness_logic.core.classification.stage1 import (
    CnCandidateRetriever,
    ProductClassificationInput,
    Stage1ResponseValidationReport,
)
from bussiness_logic.core.decision_flow.decision_policy import (
    Stage1DecisionPolicy,
)
from bussiness_logic.core.decision_flow.traversal import (
    Stage1TraversalController,
)


def _Row(
    heading: str,
    subheading: str,
    cn8: str,
) -> dict[str, str]:
    return {
        "chapter": "19",
        "chapter_description": "noodles",
        "chapter_keywords": "noodles",
        "heading": heading,
        "heading_description": "noodles",
        "heading_keywords": "noodles",
        "subheading": subheading,
        "subheading_description": "noodles",
        "subheading_keywords": "noodles",
        "cn": cn8,
        "cn_description": "noodles",
        "cn_keywords": "noodles",
    }


def _BuildFixture() -> tuple[
    CnCandidateRetriever,
    ProductClassificationInput,
]:
    retriever = CnCandidateRetriever(Path("."), Path("."))
    retriever._rowsByDomainScope = {
        "food": [
            _Row("1902", "190219", "19021910"),
            _Row("1902", "190220", "19022010"),
            _Row("1905", "190590", "19059080"),
        ],
    }
    productInput = ProductClassificationInput(
        productName="noodles",
        shortDescription="",
        productDomain="food",
        domainScopes=["food"],
    )
    return retriever, productInput


def test_decision_uses_first_conflicting_hierarchy_level() -> None:
    retriever, productInput = _BuildFixture()
    candidate = retriever.FindCandidates(productInput, topK=1)[0]
    validationReport = Stage1ResponseValidationReport(
        isValid=True,
        parsedResponse={
            "classification_result": {
                "candidate_reviews": [
                    {
                        "hs8": candidate.hs8,
                        "status": "unlikely_candidate",
                        "classification_path_review": {
                            "hs2": {"consistency": "consistent"},
                            "hs4": {"consistency": "conflicting"},
                            "hs6": {"consistency": "conflicting"},
                            "cn8": {"consistency": "conflicting"},
                        },
                    },
                ],
            },
        },
    )

    decision = Stage1DecisionPolicy().BuildDecision(
        validationReport,
        [candidate],
    )

    assert decision.backtrackingRecommended is True
    assert decision.backtrackingTargetLevel == "hs4"


def test_hs6_backtracking_stays_in_current_hs4_and_excludes_visited_cn8() -> None:
    retriever, productInput = _BuildFixture()
    currentCandidate = retriever.FindCandidates(productInput, topK=1)[0]

    candidates = retriever.FindBacktrackingCandidates(
        productInput=productInput,
        currentCandidates=[currentCandidate],
        targetLevel="hs6",
        excludedHs8Codes=[currentCandidate.hs8],
        topK=5,
    )

    assert [candidate.hs8 for candidate in candidates] == ["19022010"]
    assert all(candidate.hs4Code == currentCandidate.hs4Code for candidate in candidates)


def test_traversal_does_not_retry_after_configured_boundary() -> None:
    retriever, productInput = _BuildFixture()
    currentCandidate = retriever.FindCandidates(productInput, topK=1)[0]
    validationReport = Stage1ResponseValidationReport(
        isValid=True,
        parsedResponse={
            "classification_result": {
                "candidate_reviews": [
                    {
                        "hs8": currentCandidate.hs8,
                        "status": "unlikely_candidate",
                    },
                ],
            },
        },
    )
    decisionPolicy = Stage1DecisionPolicy()
    decision = decisionPolicy.BuildDecision(
        validationReport,
        [currentCandidate],
    )

    candidates = Stage1TraversalController(
        decisionPolicy=decisionPolicy,
    ).BuildBacktrackingCandidates(
        productInput=productInput,
        currentCandidates=[currentCandidate],
        decisionReport=decision,
        candidateRetriever=retriever,
        completedRetryCount=1,
        maxRetryCount=1,
    )

    assert candidates == []
