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
    candidate = retriever.FindCandidates(productInput, topK=1)[0].model_copy(
        update={
            "score": 0.4,
            "primaryEvidenceMatches": [],
            "secondaryEvidenceMatches": [],
            "weakEvidenceMatches": ["noodles"],
        },
    )
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


def test_static_evidence_candidate_is_retained_before_backtracking() -> None:
    retriever, productInput = _BuildFixture()
    supportedCandidate = retriever.FindCandidates(productInput, topK=1)[0]
    weakCandidate = supportedCandidate.model_copy(
        update={
            "hs8": "21069098",
            "hs4Code": "2106",
            "hs6Code": "210690",
            "score": 0.4,
            "primaryEvidenceMatches": [],
            "secondaryEvidenceMatches": [],
            "weakEvidenceMatches": ["기타"],
        },
    )
    validationReport = Stage1ResponseValidationReport(
        isValid=True,
        parsedResponse={
            "classification_result": {
                "candidate_reviews": [
                    {
                        "hs8": supportedCandidate.hs8,
                        "status": "unlikely_candidate",
                    },
                    {
                        "hs8": weakCandidate.hs8,
                        "status": "unlikely_candidate",
                    },
                ],
            },
        },
    )

    decision = Stage1DecisionPolicy().BuildDecision(
        validationReport,
        [supportedCandidate, weakCandidate],
    )
    traversal = Stage1TraversalController().BuildFromDecision(
        decision,
        [supportedCandidate, weakCandidate],
    )

    assert decision.decisionStatus == "deterministic_evidence_conflict_needs_review"
    assert decision.backtrackingRecommended is False
    assert decision.recommendedCandidateHs8 == supportedCandidate.hs8
    assert decision.deterministicEvidenceRetainedHs8Codes == [supportedCandidate.hs8]
    assert decision.unlikelyCandidateHs8Codes == [weakCandidate.hs8]
    assert traversal.retainedCandidateHs8Codes == [supportedCandidate.hs8]
    assert traversal.rejectedCandidateHs8Codes == [weakCandidate.hs8]


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
    currentCandidate = retriever.FindCandidates(productInput, topK=1)[0].model_copy(
        update={
            "score": 0.4,
            "primaryEvidenceMatches": [],
            "secondaryEvidenceMatches": [],
            "weakEvidenceMatches": ["noodles"],
        },
    )
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
