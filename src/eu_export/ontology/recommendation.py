"""Stage 1 classification recommendation report."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from eu_export.ontology.classification import (
    CnCandidate,
    ProductClassificationInput,
    Stage1ClassificationResponseValidationReport,
    Stage1DecisionReport,
    Stage1EvidencePackage,
)
from eu_export.ontology.traversal import Stage1TraversalReport
from eu_export.utils import NormalizeWhitespace


@dataclass(frozen=True)
class Stage1ClassificationRecommendationReport:
    """LLM 후보 리뷰와 traversal 결과를 제품 단위 추천 의견으로 요약한다."""

    productName: Optional[str]
    productDomain: str
    recommendationLevel: str
    recommendedCandidate: Optional[Dict[str, Any]] = None
    retainedCandidates: List[Dict[str, Any]] = field(default_factory=list)
    rejectedCandidatesSummary: List[Dict[str, Any]] = field(default_factory=list)
    backtrackingSummary: Dict[str, Any] = field(default_factory=dict)
    keyEvidenceRefs: List[str] = field(default_factory=list)
    evidenceSummary: List[Dict[str, Any]] = field(default_factory=list)
    remainingRisks: List[str] = field(default_factory=list)
    humanReviewRequired: bool = True
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "product_name": self.productName,
            "product_domain": self.productDomain,
            "recommendation_level": self.recommendationLevel,
            "recommended_candidate": self.recommendedCandidate,
            "retained_candidates": list(self.retainedCandidates),
            "rejected_candidates_summary": list(self.rejectedCandidatesSummary),
            "backtracking_summary": dict(self.backtrackingSummary),
            "key_evidence_refs": list(self.keyEvidenceRefs),
            "evidence_summary": list(self.evidenceSummary),
            "remaining_risks": list(self.remainingRisks),
            "human_review_required": self.humanReviewRequired,
            "limitations": list(self.limitations),
        }


class Stage1ClassificationRecommendationReportBuilder:
    """Stage 1 결과 묶음을 user-facing recommendation report로 변환한다."""

    def Build(
        self,
        productInput: ProductClassificationInput,
        candidates: Sequence[CnCandidate],
        validationReport: Stage1ClassificationResponseValidationReport,
        decisionReport: Stage1DecisionReport,
        traversalReport: Stage1TraversalReport,
        evidencePackage: Optional[Stage1EvidencePackage] = None,
        backtrackingSummary: Optional[Mapping[str, Any]] = None,
    ) -> Stage1ClassificationRecommendationReport:
        candidateByHs8 = {candidate.hs8: candidate for candidate in candidates}
        candidateReviews = self._ReadCandidateReviews(validationReport)
        reviewByHs8 = {
            str(review.get("hs8")): review
            for review in candidateReviews
            if isinstance(review.get("hs8"), str)
        }

        recommendedCandidate = None
        retainedCandidates: List[Dict[str, Any]] = []
        rejectedCandidatesSummary: List[Dict[str, Any]] = []

        for candidateCode in traversalReport.retainedCandidateHs8Codes:
            candidateRecord = self._BuildCandidateRecord(
                candidateByHs8.get(candidateCode),
                reviewByHs8.get(candidateCode, {}),
            )
            if candidateCode == traversalReport.recommendedCandidateHs8:
                recommendedCandidate = candidateRecord
            else:
                retainedCandidates.append(candidateRecord)

        for candidateCode in traversalReport.rejectedCandidateHs8Codes:
            rejectedCandidatesSummary.append(
                self._BuildCandidateRecord(
                    candidateByHs8.get(candidateCode),
                    reviewByHs8.get(candidateCode, {}),
                    summaryOnly=True,
                )
            )

        return Stage1ClassificationRecommendationReport(
            productName=productInput.productName,
            productDomain=productInput.productDomain,
            recommendationLevel=self._BuildRecommendationLevel(decisionReport),
            recommendedCandidate=recommendedCandidate,
            retainedCandidates=retainedCandidates,
            rejectedCandidatesSummary=rejectedCandidatesSummary,
            backtrackingSummary=dict(backtrackingSummary or {}),
            keyEvidenceRefs=list(decisionReport.evidenceRefs),
            evidenceSummary=self._BuildEvidenceSummary(
                decisionReport.evidenceRefs,
                evidencePackage,
            ),
            remainingRisks=self._BuildUniqueStrings(
                [
                    *decisionReport.missingInformation,
                    *traversalReport.missingInformation,
                ]
            ),
            humanReviewRequired=True,
            limitations=self._BuildUniqueStrings(
                [
                    *decisionReport.limitations,
                    *traversalReport.limitations,
                    (
                        "This recommendation is a provisional system recommendation "
                        "for human review, not a final legal/customs determination."
                    ),
                ]
            ),
        )

    def _BuildCandidateRecord(
        self,
        candidate: Optional[CnCandidate],
        candidateReview: Mapping[str, Any],
        summaryOnly: bool = False,
    ) -> Dict[str, Any]:
        record = {
            "hs8": candidate.hs8 if candidate is not None else candidateReview.get("hs8"),
            "hs6_code": (
                candidate.hs6Code
                if candidate is not None
                else candidateReview.get("hs6_code")
            ),
            "status": candidateReview.get("status"),
            "reason": candidateReview.get("reason"),
            "evidence_refs": list(candidateReview.get("evidence_refs", []))
            if isinstance(candidateReview.get("evidence_refs"), list)
            else [],
        }
        if summaryOnly:
            record["conflicting_or_exclusion_facts"] = list(
                candidateReview.get("conflicting_or_exclusion_facts", []),
            ) if isinstance(
                candidateReview.get("conflicting_or_exclusion_facts"),
                list,
            ) else []
            return record

        record.update(
            {
                "score": candidate.score if candidate is not None else None,
                "matched_terms": (
                    list(candidate.matchedTerms)
                    if candidate is not None
                    else []
                ),
                "supporting_product_facts": list(
                    candidateReview.get("supporting_product_facts", []),
                ) if isinstance(
                    candidateReview.get("supporting_product_facts"),
                    list,
                ) else [],
                "conflicting_or_exclusion_facts": list(
                    candidateReview.get("conflicting_or_exclusion_facts", []),
                ) if isinstance(
                    candidateReview.get("conflicting_or_exclusion_facts"),
                    list,
                ) else [],
                "missing_information": list(
                    candidateReview.get("missing_information", []),
                ) if isinstance(
                    candidateReview.get("missing_information"),
                    list,
                ) else [],
                "hard_conditions": (
                    candidate.hardConditions if candidate is not None else ""
                ),
                "combined_description": (
                    candidate.combinedDescription if candidate is not None else ""
                ),
            }
        )
        return record

    def _BuildEvidenceSummary(
        self,
        evidenceRefs: Sequence[str],
        evidencePackage: Optional[Stage1EvidencePackage],
    ) -> List[Dict[str, Any]]:
        if evidencePackage is None:
            return []
        evidenceRecordById = {
            evidenceRecord.evidenceId: evidenceRecord
            for evidenceRecord in evidencePackage.evidenceRecords
        }
        evidenceSummary: List[Dict[str, Any]] = []
        for evidenceRef in evidenceRefs:
            evidenceRecord = evidenceRecordById.get(evidenceRef)
            if evidenceRecord is None:
                continue
            text = NormalizeWhitespace(evidenceRecord.text)
            evidenceSummary.append(
                {
                    "evidence_id": evidenceRecord.evidenceId,
                    "evidence_type": evidenceRecord.evidenceType,
                    "source_name": evidenceRecord.sourceName,
                    "source_ref": evidenceRecord.sourceRef,
                    "candidate_hs8": evidenceRecord.candidateHs8,
                    "text_preview": text[:300],
                }
            )
        return evidenceSummary

    def _BuildRecommendationLevel(
        self,
        decisionReport: Stage1DecisionReport,
    ) -> str:
        if decisionReport.decisionStatus == "single_strong_candidate_for_human_review":
            return "provisional_system_recommendation"
        if decisionReport.decisionStatus == "possible_candidates_need_review":
            return "tentative_system_recommendation"
        if decisionReport.decisionStatus == "multiple_strong_candidates_need_review":
            return "candidate_comparison_required"
        if decisionReport.decisionStatus == "insufficient_information_before_code_selection":
            return "insufficient_information"
        if decisionReport.decisionStatus == "backtracking_recommended":
            return "backtracking_required"
        return "invalid_or_unavailable"

    def _ReadCandidateReviews(
        self,
        validationReport: Stage1ClassificationResponseValidationReport,
    ) -> List[Mapping[str, Any]]:
        classificationResult = validationReport.parsedResponse.get(
            "classification_result",
        )
        if not isinstance(classificationResult, Mapping):
            return []
        candidateReviews = classificationResult.get("candidate_reviews")
        if not isinstance(candidateReviews, list):
            return []
        return [
            candidateReview
            for candidateReview in candidateReviews
            if isinstance(candidateReview, Mapping)
        ]

    def _BuildUniqueStrings(self, values: Sequence[Any]) -> List[str]:
        uniqueValues: List[str] = []
        seenValues: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            normalizedValue = NormalizeWhitespace(value)
            if normalizedValue == "" or normalizedValue in seenValues:
                continue
            uniqueValues.append(normalizedValue)
            seenValues.add(normalizedValue)
        return uniqueValues
