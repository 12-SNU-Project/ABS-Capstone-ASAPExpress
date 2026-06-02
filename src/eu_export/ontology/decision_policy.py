"""Stage 1 classification decision policy."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from eu_export.ontology.classification import (
    CnCandidate,
    Stage1ClassificationResponseValidationReport,
)
from eu_export.utils import NormalizeWhitespace


@dataclass(frozen=True)
class Stage1DecisionReport:
    """검증된 Stage 1 후보 검토 응답을 다음 처리 단계용 결정 요약으로 정리한다."""

    decisionStatus: str
    recommendedCandidateHs8: Optional[str] = None
    strongCandidateHs8Codes: List[str] = field(default_factory=list)
    possibleCandidateHs8Codes: List[str] = field(default_factory=list)
    unlikelyCandidateHs8Codes: List[str] = field(default_factory=list)
    insufficientInformationHs8Codes: List[str] = field(default_factory=list)
    candidateStatusByHs8: Dict[str, str] = field(default_factory=dict)
    backtrackingRecommended: bool = False
    backtrackingTargetLevel: Optional[str] = None
    backtrackingReason: Optional[str] = None
    missingInformation: List[str] = field(default_factory=list)
    evidenceRefs: List[str] = field(default_factory=list)
    humanReviewRequired: bool = True
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "decision_status": self.decisionStatus,
            "recommended_candidate_hs8": self.recommendedCandidateHs8,
            "strong_candidate_hs8_codes": list(self.strongCandidateHs8Codes),
            "possible_candidate_hs8_codes": list(self.possibleCandidateHs8Codes),
            "unlikely_candidate_hs8_codes": list(self.unlikelyCandidateHs8Codes),
            "insufficient_information_hs8_codes": list(
                self.insufficientInformationHs8Codes,
            ),
            "candidate_status_by_hs8": dict(self.candidateStatusByHs8),
            "backtracking_recommended": self.backtrackingRecommended,
            "backtracking_target_level": self.backtrackingTargetLevel,
            "backtracking_reason": self.backtrackingReason,
            "missing_information": list(self.missingInformation),
            "evidence_refs": list(self.evidenceRefs),
            "human_review_required": self.humanReviewRequired,
            "limitations": list(self.limitations),
        }


class Stage1DecisionPolicy:
    """검증된 후보 리뷰 결과를 다음 단계의 진행/되돌림 판단으로 변환한다."""

    def BuildDecision(
        self,
        validationReport: Stage1ClassificationResponseValidationReport,
        candidates: Sequence[CnCandidate],
    ) -> Stage1DecisionReport:
        if not validationReport.isValid:
            return Stage1DecisionReport(
                decisionStatus="invalid_response_requires_retry",
                limitations=[
                    "Validator errors must be fixed before classification traversal continues.",
                ],
            )

        classificationResult = validationReport.parsedResponse.get(
            "classification_result",
        )
        if not isinstance(classificationResult, Mapping):
            return Stage1DecisionReport(
                decisionStatus="invalid_response_requires_retry",
                limitations=[
                    "classification_result is unavailable after validation.",
                ],
            )

        candidateOrder = {
            candidate.hs8: index
            for index, candidate in enumerate(candidates)
        }
        candidateStatusByHs8: Dict[str, str] = {}
        missingInformation: List[str] = []
        evidenceRefs: List[str] = []

        candidateReviews = classificationResult.get("candidate_reviews")
        if isinstance(candidateReviews, list):
            for candidateReview in candidateReviews:
                if not isinstance(candidateReview, Mapping):
                    continue
                hs8 = candidateReview.get("hs8")
                status = candidateReview.get("status")
                if not isinstance(hs8, str) or hs8 not in candidateOrder:
                    continue
                if not isinstance(status, str):
                    continue
                candidateStatusByHs8[hs8] = status
                self._ExtendUniqueStrings(
                    missingInformation,
                    candidateReview.get("missing_information"),
                )
                self._ExtendUniqueStrings(
                    evidenceRefs,
                    candidateReview.get("evidence_refs"),
                )

        self._ExtendUniqueStrings(
            missingInformation,
            classificationResult.get("not_enough_information"),
        )

        strongCandidates = self._BuildOrderedStatusCodes(
            candidateStatusByHs8,
            candidateOrder,
            "strong_candidate",
        )
        possibleCandidates = self._BuildOrderedStatusCodes(
            candidateStatusByHs8,
            candidateOrder,
            "possible_candidate",
        )
        unlikelyCandidates = self._BuildOrderedStatusCodes(
            candidateStatusByHs8,
            candidateOrder,
            "unlikely_candidate",
        )
        insufficientInformationCandidates = self._BuildOrderedStatusCodes(
            candidateStatusByHs8,
            candidateOrder,
            "insufficient_information",
        )

        if len(strongCandidates) == 1:
            decisionStatus = "single_strong_candidate_for_human_review"
            recommendedCandidateHs8 = strongCandidates[0]
            backtrackingRecommended = False
            backtrackingTargetLevel = None
            backtrackingReason = None
        elif len(strongCandidates) > 1:
            decisionStatus = "multiple_strong_candidates_need_review"
            recommendedCandidateHs8 = None
            backtrackingRecommended = False
            backtrackingTargetLevel = None
            backtrackingReason = None
        elif possibleCandidates:
            decisionStatus = "possible_candidates_need_review"
            recommendedCandidateHs8 = possibleCandidates[0]
            backtrackingRecommended = False
            backtrackingTargetLevel = None
            backtrackingReason = None
        elif insufficientInformationCandidates:
            decisionStatus = "insufficient_information_before_code_selection"
            recommendedCandidateHs8 = None
            backtrackingRecommended = False
            backtrackingTargetLevel = None
            backtrackingReason = None
        else:
            decisionStatus = "backtracking_recommended"
            recommendedCandidateHs8 = None
            backtrackingRecommended = True
            backtrackingTargetLevel = "hs6_or_parent_candidate_scope"
            backtrackingReason = (
                "No reviewed CN8 candidate remained plausible; regenerate "
                "candidate set from the parent HS/CN hierarchy."
            )

        return Stage1DecisionReport(
            decisionStatus=decisionStatus,
            recommendedCandidateHs8=recommendedCandidateHs8,
            strongCandidateHs8Codes=strongCandidates,
            possibleCandidateHs8Codes=possibleCandidates,
            unlikelyCandidateHs8Codes=unlikelyCandidates,
            insufficientInformationHs8Codes=insufficientInformationCandidates,
            candidateStatusByHs8=candidateStatusByHs8,
            backtrackingRecommended=backtrackingRecommended,
            backtrackingTargetLevel=backtrackingTargetLevel,
            backtrackingReason=backtrackingReason,
            missingInformation=missingInformation,
            evidenceRefs=evidenceRefs,
            limitations=[
                "Stage 1 decision policy ranks review outcomes but does not make a final legal/customs determination.",
                "Human review remains required even when one candidate is prioritized.",
            ],
        )

    def _BuildOrderedStatusCodes(
        self,
        candidateStatusByHs8: Mapping[str, str],
        candidateOrder: Mapping[str, int],
        status: str,
    ) -> List[str]:
        return sorted(
            [
                hs8
                for hs8, candidateStatus in candidateStatusByHs8.items()
                if candidateStatus == status
            ],
            key=lambda hs8: candidateOrder.get(hs8, 9999),
        )

    def _ExtendUniqueStrings(
        self,
        target: List[str],
        values: Any,
    ) -> None:
        if not isinstance(values, list):
            return
        seenValues = set(target)
        for value in values:
            if not isinstance(value, str):
                continue
            normalizedValue = NormalizeWhitespace(value)
            if normalizedValue == "" or normalizedValue in seenValues:
                continue
            target.append(normalizedValue)
            seenValues.add(normalizedValue)
