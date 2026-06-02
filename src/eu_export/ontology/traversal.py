"""Stage 1 classification traversal controller."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from eu_export.ontology.classification import (
    CnCandidate,
    CnCandidateRetriever,
    DEFAULT_CN_CANDIDATE_TOP_K,
    ProductClassificationInput,
    Stage1ClassificationResponseValidationReport,
)
from eu_export.ontology.decision_policy import (
    Stage1DecisionPolicy,
    Stage1DecisionReport,
)


DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT = 1


@dataclass(frozen=True)
class Stage1TraversalReport:
    """Stage 1 decision 결과를 다음 pipeline action으로 변환한 report."""

    traversalStatus: str
    nextAction: str
    decisionStatus: str
    currentCandidateHs8Codes: List[str] = field(default_factory=list)
    retainedCandidateHs8Codes: List[str] = field(default_factory=list)
    rejectedCandidateHs8Codes: List[str] = field(default_factory=list)
    recommendedCandidateHs8: Optional[str] = None
    backtrackingRecommended: bool = False
    backtrackingTargetLevel: Optional[str] = None
    backtrackingReason: Optional[str] = None
    missingInformation: List[str] = field(default_factory=list)
    evidenceRefs: List[str] = field(default_factory=list)
    humanReviewRequired: bool = True
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "traversal_status": self.traversalStatus,
            "next_action": self.nextAction,
            "decision_status": self.decisionStatus,
            "current_candidate_hs8_codes": list(self.currentCandidateHs8Codes),
            "retained_candidate_hs8_codes": list(self.retainedCandidateHs8Codes),
            "rejected_candidate_hs8_codes": list(self.rejectedCandidateHs8Codes),
            "recommended_candidate_hs8": self.recommendedCandidateHs8,
            "backtracking_recommended": self.backtrackingRecommended,
            "backtracking_target_level": self.backtrackingTargetLevel,
            "backtracking_reason": self.backtrackingReason,
            "missing_information": list(self.missingInformation),
            "evidence_refs": list(self.evidenceRefs),
            "human_review_required": self.humanReviewRequired,
            "limitations": list(self.limitations),
        }


class Stage1TraversalController:
    """Stage 1 후보 검토 결과를 다음 단계 action으로 연결한다."""

    def __init__(
        self,
        decisionPolicy: Optional[Stage1DecisionPolicy] = None,
    ) -> None:
        self._decisionPolicy = decisionPolicy or Stage1DecisionPolicy()

    def BuildReport(
        self,
        validationReport: Stage1ClassificationResponseValidationReport,
        candidates: Sequence[CnCandidate],
    ) -> Stage1TraversalReport:
        decisionReport = self._decisionPolicy.BuildDecision(
            validationReport,
            candidates,
        )
        return self.BuildFromDecision(decisionReport, candidates)

    def BuildFromDecision(
        self,
        decisionReport: Stage1DecisionReport,
        candidates: Sequence[CnCandidate] = (),
    ) -> Stage1TraversalReport:
        currentCandidateHs8Codes = (
            [candidate.hs8 for candidate in candidates]
            if candidates
            else self._BuildUniqueCandidateCodes(
                [
                    decisionReport.strongCandidateHs8Codes,
                    decisionReport.possibleCandidateHs8Codes,
                    decisionReport.insufficientInformationHs8Codes,
                    decisionReport.unlikelyCandidateHs8Codes,
                ]
            )
        )
        retainedCandidateHs8Codes = self._BuildUniqueCandidateCodes(
            [
                decisionReport.strongCandidateHs8Codes,
                decisionReport.possibleCandidateHs8Codes,
                decisionReport.insufficientInformationHs8Codes,
            ]
        )

        if decisionReport.decisionStatus == "invalid_response_requires_retry":
            traversalStatus = "retry_required"
            nextAction = "retry_llm_response"
        elif decisionReport.backtrackingRecommended:
            traversalStatus = "needs_backtracking"
            nextAction = "backtrack_candidate_scope"
        elif (
            decisionReport.decisionStatus
            == "insufficient_information_before_code_selection"
        ):
            traversalStatus = "needs_more_product_information"
            nextAction = "request_missing_product_information"
        elif decisionReport.decisionStatus == "multiple_strong_candidates_need_review":
            traversalStatus = "needs_candidate_comparison"
            nextAction = "compare_retained_candidates"
        else:
            traversalStatus = "ready_for_human_review"
            nextAction = "prepare_human_review_package"

        return Stage1TraversalReport(
            traversalStatus=traversalStatus,
            nextAction=nextAction,
            decisionStatus=decisionReport.decisionStatus,
            currentCandidateHs8Codes=currentCandidateHs8Codes,
            retainedCandidateHs8Codes=retainedCandidateHs8Codes,
            rejectedCandidateHs8Codes=list(decisionReport.unlikelyCandidateHs8Codes),
            recommendedCandidateHs8=decisionReport.recommendedCandidateHs8,
            backtrackingRecommended=decisionReport.backtrackingRecommended,
            backtrackingTargetLevel=decisionReport.backtrackingTargetLevel,
            backtrackingReason=decisionReport.backtrackingReason,
            missingInformation=list(decisionReport.missingInformation),
            evidenceRefs=list(decisionReport.evidenceRefs),
            humanReviewRequired=decisionReport.humanReviewRequired,
            limitations=[
                *decisionReport.limitations,
                (
                    "BuildFromDecision selects the next pipeline action; "
                    "candidate regeneration must be called explicitly."
                ),
            ],
        )

    def BuildBacktrackingCandidates(
        self,
        productInput: ProductClassificationInput,
        currentCandidates: Sequence[CnCandidate],
        decisionReport: Stage1DecisionReport,
        candidateRetriever: CnCandidateRetriever,
        topK: int = DEFAULT_CN_CANDIDATE_TOP_K,
        visitedHs8Codes: Sequence[str] = (),
        completedRetryCount: int = 0,
        maxRetryCount: int = DEFAULT_STAGE1_TRAVERSAL_MAX_RETRY_COUNT,
    ) -> List[CnCandidate]:
        if completedRetryCount >= maxRetryCount:
            return []

        traversalReport = self.BuildFromDecision(decisionReport, currentCandidates)
        if traversalReport.nextAction != "backtrack_candidate_scope":
            return []

        excludedHs8Codes = set(visitedHs8Codes)
        excludedHs8Codes.update(
            traversalReport.rejectedCandidateHs8Codes
            or traversalReport.currentCandidateHs8Codes
        )
        return candidateRetriever.FindSiblingCandidates(
            productInput=productInput,
            currentCandidates=currentCandidates,
            excludedHs8Codes=sorted(excludedHs8Codes),
            topK=topK,
        )

    def _BuildUniqueCandidateCodes(
        self,
        codeGroups: Sequence[Sequence[str]],
    ) -> List[str]:
        candidateCodes: List[str] = []
        for codeGroup in codeGroups:
            for candidateCode in codeGroup:
                if candidateCode not in candidateCodes:
                    candidateCodes.append(candidateCode)
        return candidateCodes
