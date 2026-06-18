from types import SimpleNamespace
from typing import Any

from agents import _external_classifier as externalClassifier


def _Candidate(code: str) -> SimpleNamespace:
    return SimpleNamespace(
        hs8=code,
        hs8Description="fixture",
        retrievalSources=["heuristic"],
    )


def test_external_classifier_runs_one_bounded_backtracking_round(
    monkeypatch: Any,
) -> None:
    initialCandidate = _Candidate("19021910")
    backtrackingCandidate = _Candidate("19022010")
    roundCalls: list[list[str]] = []

    class FakeRetriever:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def FindCandidates(self, productInput: Any, topK: int) -> list[Any]:
            del productInput, topK
            return [initialCandidate]

    class FakeTraversalController:
        def BuildBacktrackingCandidates(
            self,
            **kwargs: Any,
        ) -> list[Any]:
            assert kwargs["completedRetryCount"] == 0
            assert kwargs["maxRetryCount"] == 1
            return [backtrackingCandidate]

    class FakeRecommendationBuilder:
        def Build(self, *args: Any, **kwargs: Any) -> str:
            return "fixture-recommendation"

    def RunRound(
        productInput: Any,
        candidates: list[Any],
        adapter: Any,
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
