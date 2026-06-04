"""Stage 1 classification candidate report."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from eu_export.ontology.classification import (
    CnCandidate,
    ProductClassificationInput,
    Stage1ClassificationResponseValidationReport,
    Stage1EvidencePackage,
)
from eu_export.ontology.decision_policy import Stage1DecisionReport
from eu_export.ontology.traversal import Stage1TraversalReport
from eu_export.utils import NormalizeWhitespace


@dataclass(frozen=True)
class Stage1ClassificationRecommendationReport:
    """LLM 후보 리뷰와 traversal 결과를 제품 단위 후보 검토 의견으로 요약한다."""

    productName: Optional[str]
    productDomain: str
    recommendationLevel: str
    candidateOutputMode: str = "candidate_generation_for_human_review"
    candidateGenerationProcess: Dict[str, Any] = field(default_factory=dict)
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
            "candidate_output_mode": self.candidateOutputMode,
            "recommendation_level": self.recommendationLevel,
            "candidate_generation_process": dict(self.candidateGenerationProcess),
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
    """Stage 1 결과 묶음을 user-facing 후보 검토 report로 변환한다."""

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
            if candidateCode == decisionReport.recommendedCandidateHs8:
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
            candidateGenerationProcess=self._BuildCandidateGenerationProcess(
                productInput,
                candidates,
            ),
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
                decisionReport.missingInformation,
            ),
            humanReviewRequired=True,
            limitations=self._BuildUniqueStrings(
                [
                    *decisionReport.limitations,
                    (
                        "Traversal selected the next pipeline action: "
                        "{0}.".format(traversalReport.nextAction)
                    ),
                    (
                        "This report surfaces review candidates for human review; "
                        "it is not a final legal/customs determination."
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
            "classification_path_review": (
                dict(candidateReview.get("classification_path_review", {}))
                if isinstance(
                    candidateReview.get("classification_path_review"),
                    Mapping,
                )
                else {}
            ),
            "classification_rule_review": (
                dict(candidateReview.get("classification_rule_review", {}))
                if isinstance(
                    candidateReview.get("classification_rule_review"),
                    Mapping,
                )
                else {}
            ),
            "similar_ebti_cases": list(
                candidateReview.get("similar_ebti_cases", []),
            )
            if isinstance(candidateReview.get("similar_ebti_cases"), list)
            else [],
        }
        if candidate is not None:
            record["candidate_scoring_detail"] = self._BuildCandidateScoringDetail(
                candidate,
            )
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
                "code_hierarchy": (
                    candidate.ToDict().get("code_hierarchy")
                    if candidate is not None
                    else {}
                ),
                "classification_rule_texts": (
                    candidate.ToDict().get("classification_rule_texts")
                    if candidate is not None
                    else {}
                ),
                "hard_conditions": (
                    candidate.hardConditions if candidate is not None else ""
                ),
                "combined_description": (
                    candidate.combinedDescription if candidate is not None else ""
                ),
            }
        )
        return record

    def _BuildCandidateGenerationProcess(
        self,
        productInput: ProductClassificationInput,
        candidates: Sequence[CnCandidate],
    ) -> Dict[str, Any]:
        return {
            "output_purpose": (
                "Generate HS6/CN8 candidates and explain why each candidate "
                "was surfaced. This is not a final classification decision."
            ),
            "domain_scopes": list(productInput.domainScopes),
            "search_text_length": len(productInput.BuildSearchText()),
            "scoring_rule": {
                "include_rule_keyword_match": "+4 per match",
                "search_keyword_match": "+2 per match",
                "description_token_match": "+1 per match",
                "exclude_rule_match": "candidate score forced to 0",
            },
            "generated_candidate_count": len(candidates),
            "generated_candidate_codes": [candidate.hs8 for candidate in candidates],
            "generated_candidates": [
                {
                    "hs8": candidate.hs8,
                    "hs6_code": candidate.hs6Code,
                    **self._BuildCandidateScoringDetail(candidate),
                }
                for candidate in candidates
            ],
            "human_review_note": (
                "The first retained candidate is a priority review candidate, "
                "not a legally confirmed CN code."
            ),
        }

    def _BuildCandidateScoringDetail(
        self,
        candidate: CnCandidate,
    ) -> Dict[str, Any]:
        candidateData = candidate.ToDict()
        return {
            "score": candidate.score,
            "score_breakdown": candidateData.get("score_breakdown", {}),
            "matched_terms": list(candidate.matchedTerms),
            "include_rule_matches": list(candidate.includeRuleMatches),
            "search_keyword_matches": list(candidate.searchKeywordMatches),
            "description_matches": list(candidate.descriptionMatches),
            "exclude_rule_matches": list(candidate.excludeRuleMatches),
            "code_hierarchy": candidateData.get("code_hierarchy", {}),
            "classification_rule_texts": candidateData.get(
                "classification_rule_texts",
                {},
            ),
            "combined_description": candidate.combinedDescription,
        }

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
            return "single_priority_candidate_for_human_review"
        if decisionReport.decisionStatus == "possible_candidates_need_review":
            return "priority_candidate_for_human_review"
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
