from types import SimpleNamespace
import json

import pytest

from agents import candiate_classfier as externalClassifier
from bussiness_logic.core.classification.hierarchical_beam import (
    HierarchySearchBoundary,
)


def _Candidate(code: str) -> SimpleNamespace:
    return SimpleNamespace(
        hs8=code,
        hs8Description="fixture",
        retrievalSources=["heuristic"],
    )


def test_external_classifier_runs_one_bounded_backtracking_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialCandidate = _Candidate("19021910")
    backtrackingCandidate = _Candidate("19022010")
    roundCalls: list[list[str]] = []

    class FakeRetriever:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def FindCandidates(
            self,
            productInput: object,
            topK: int,
            boundary: HierarchySearchBoundary | None = None,
        ) -> list[object]:
            del productInput, topK, boundary
            return [initialCandidate]

    class FakeTraversalController:
        def BuildBacktrackingCandidates(
            self,
            **kwargs: object,
        ) -> list[object]:
            assert kwargs["completedRetryCount"] == 0
            assert kwargs["maxRetryCount"] == 1
            return [backtrackingCandidate]

    class FakeRecommendationBuilder:
        def Build(self, *args: object, **kwargs: object) -> str:
            return "fixture-recommendation"

    def RunRound(
        productInput: object,
        candidates: list[object],
        adapter: object,
    ) -> externalClassifier._Stage1ReviewRound:
        del productInput, adapter
        roundCalls.append([candidate.hs8 for candidate in candidates])
        needsBacktracking = len(roundCalls) == 1
        return externalClassifier._Stage1ReviewRound(
            candidates=list(candidates),
            evidencePackage=object(),
            validationReport=object(),
            decisionReport=object(),
            traversalReport=SimpleNamespace(
                nextAction=(
                    "backtrack_candidate_scope"
                    if needsBacktracking
                    else "prepare_human_review_package"
                ),
            ),
            responseText="{}",
            modelName="fixture",
            promptText="fixture",
        )

    monkeypatch.setattr(
        externalClassifier,
        "CnCandidateRetriever",
        FakeRetriever,
    )
    monkeypatch.setattr(
        externalClassifier,
        "build_semantic_candidate_index",
        lambda retriever: (None, {"status": "disabled"}),
    )
    monkeypatch.setattr(
        externalClassifier,
        "Stage1TraversalController",
        FakeTraversalController,
    )
    monkeypatch.setattr(
        externalClassifier,
        "Stage1RecommendationReportBuilder",
        FakeRecommendationBuilder,
    )
    monkeypatch.setattr(externalClassifier, "_RunStage1ReviewRound", RunRound)

    result = externalClassifier.run_external_classifier(
        {"observed_facts": {"product_name": "fixture"}},
        domain_scope="food",
        runtime_adapter=object(),
        top_k_candidates=1,
    )

    assert roundCalls == [["19021910"], ["19022010"]]
    assert [candidate.hs8 for candidate in result.candidates] == ["19022010"]
    assert result.error is None


def test_external_classifier_falls_back_when_routed_scope_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallbackCandidate = _Candidate("21039090")
    seenBoundaries: list[HierarchySearchBoundary | None] = []

    class FakeRetriever:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def FindCandidates(
            self,
            productInput: object,
            topK: int,
            boundary: HierarchySearchBoundary | None = None,
        ) -> list[object]:
            del productInput, topK
            seenBoundaries.append(boundary)
            return [] if boundary is not None else [fallbackCandidate]

    class FakeRecommendationBuilder:
        def Build(self, *args: object, **kwargs: object) -> str:
            return "fixture-recommendation"

    def RunRound(
        productInput: object,
        candidates: list[object],
        adapter: object,
    ) -> externalClassifier._Stage1ReviewRound:
        del productInput, adapter
        return externalClassifier._Stage1ReviewRound(
            candidates=list(candidates),
            evidencePackage=object(),
            validationReport=object(),
            decisionReport=object(),
            traversalReport=SimpleNamespace(
                nextAction="prepare_human_review_package",
            ),
            responseText="{}",
            modelName="fixture",
            promptText="fixture",
        )

    monkeypatch.setattr(
        externalClassifier,
        "CnCandidateRetriever",
        FakeRetriever,
    )
    monkeypatch.setattr(
        externalClassifier,
        "build_semantic_candidate_index",
        lambda retriever: (None, {"status": "disabled"}),
    )
    monkeypatch.setattr(
        externalClassifier,
        "Stage1RecommendationReportBuilder",
        FakeRecommendationBuilder,
    )
    monkeypatch.setattr(externalClassifier, "_RunStage1ReviewRound", RunRound)

    result = externalClassifier.run_external_classifier(
        {"observed_facts": {"product_name": "fixture"}},
        domain_scope="food",
        runtime_adapter=object(),
        top_k_candidates=1,
        routing_context={
            "routing_context_id": "route_001",
            "allowed_hs2": ["19"],
            "enforce_hs2_boundary": True,
            "fallback_allowed": True,
        },
    )

    assert len(seenBoundaries) == 2
    assert seenBoundaries[0] is not None
    assert seenBoundaries[0].Allows("hs2", "19")
    assert seenBoundaries[1] is None
    assert [candidate.hs8 for candidate in result.candidates] == ["21039090"]


def test_unreviewed_candidate_defaults_to_insufficient_information() -> None:
    productInput = SimpleNamespace(
        productName="fixture pasta",
        productDomain="food",
        domainScopes=["food"],
        structuredProductFacts=[],
        unresolvedProductFacts=[],
        productFactConflicts=[],
        normalizedOcrFactTexts=[],
        BuildSearchText=lambda: "fixture pasta",
    )
    expanded = json.loads(
        externalClassifier._expand_compact_decision_to_stage1_json(
            {
                "selected_hs8": "19023090",
                "candidate_reviews": [
                    {
                        "hs8": "19023090",
                        "status": "strong_candidate",
                    }
                ],
            },
            productInput,
            [_Candidate("19023090"), _Candidate("19022010")],
        )
    )

    reviews = {
        review["hs8"]: review["status"]
        for review in expanded["classification_result"]["candidate_reviews"]
    }
    assert reviews["19023090"] == "strong_candidate"
    assert reviews["19022010"] == "insufficient_information"
