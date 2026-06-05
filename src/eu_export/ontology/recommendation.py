"""Stage 1 classification candidate report."""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from eu_export.ontology.classification import (
    CnCandidate,
    ProductClassificationInput,
    Stage1ResponseValidationReport,
    Stage1EvidencePackage,
)
from eu_export.ontology.decision_policy import Stage1DecisionReport
from eu_export.ontology.traversal import Stage1TraversalReport
from eu_export.utils import NormalizeWhitespace


class Stage1RecommendationReport(BaseModel):
    """LLM 후보 리뷰와 traversal 결과를 제품 단위 후보 검토 의견으로 요약한다."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    productName: Optional[str] = Field(alias="product_name")
    productDomain: str = Field(alias="product_domain")
    recommendationLevel: str = Field(alias="recommendation_level")
    candidateOutputMode: str = Field(
        default="candidate_generation_for_human_review",
        alias="candidate_output_mode",
    )
    candidateGenerationProcess: Dict[str, Any] = Field(
        default_factory=dict,
        alias="candidate_generation_process",
    )
    recommendedCandidate: Optional[Dict[str, Any]] = Field(
        default=None,
        alias="recommended_candidate",
    )
    retainedCandidates: List[Dict[str, Any]] = Field(
        default_factory=list,
        alias="retained_candidates",
    )
    rejectedCandidatesSummary: List[Dict[str, Any]] = Field(
        default_factory=list,
        alias="rejected_candidates_summary",
    )
    backtrackingSummary: Dict[str, Any] = Field(
        default_factory=dict,
        alias="backtracking_summary",
    )
    keyEvidenceRefs: List[str] = Field(
        default_factory=list,
        alias="key_evidence_refs",
    )
    evidenceSummary: List[Dict[str, Any]] = Field(
        default_factory=list,
        alias="evidence_summary",
    )
    remainingRisks: List[str] = Field(
        default_factory=list,
        alias="remaining_risks",
    )
    humanReviewRequired: bool = Field(
        default=True,
        alias="human_review_required",
    )
    limitations: List[str] = Field(default_factory=list)


class Stage1RecommendationReportBuilder:
    """Stage 1 결과 묶음을 user-facing 후보 검토 report로 변환한다."""

    def Build(
        self,
        productInput: ProductClassificationInput,
        candidates: Sequence[CnCandidate],
        validationReport: Stage1ResponseValidationReport,
        decisionReport: Stage1DecisionReport,
        traversalReport: Stage1TraversalReport,
        evidencePackage: Optional[Stage1EvidencePackage] = None,
        backtrackingSummary: Optional[Mapping[str, Any]] = None,
    ) -> Stage1RecommendationReport:
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

        return Stage1RecommendationReport(
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
            record["candidate_reference"] = {
                "code_hierarchy": {
                    "hs2": {
                        "code": candidate.hs2Code,
                        "description": candidate.hs2Description,
                    },
                    "hs4": {
                        "code": candidate.hs4Code,
                        "description": candidate.hs4Description,
                    },
                    "hs6": {
                        "code": candidate.hs6Code,
                        "description": candidate.hs6Description,
                    },
                    "cn8": {
                        "code": candidate.hs8Code or candidate.hs8,
                        "description": candidate.hs8Description,
                    },
                },
                "classification_rule_texts": {
                    "include_rule_keywords": candidate.includeRuleKeywords,
                    "exclude_rule_keywords": candidate.excludeRuleKeywords,
                    "hard_conditions": candidate.hardConditions,
                },
                "combined_description": candidate.combinedDescription,
            }
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
        return {
            "score": candidate.score,
            "score_breakdown": {
                "include_rule_points": 4.0 * len(candidate.includeRuleMatches),
                "search_keyword_points": 2.0 * len(candidate.searchKeywordMatches),
                "description_points": 1.0 * len(candidate.descriptionMatches),
                "exclude_rule_triggered": len(candidate.excludeRuleMatches) > 0,
                "formula": (
                    "include_rule_keywords*4 + search_keywords*2 + "
                    "description_matches*1; exclude_rule match forces score 0"
                ),
            },
            "matched_terms": list(candidate.matchedTerms),
            "include_rule_matches": list(candidate.includeRuleMatches),
            "search_keyword_matches": list(candidate.searchKeywordMatches),
            "description_matches": list(candidate.descriptionMatches),
            "exclude_rule_matches": list(candidate.excludeRuleMatches),
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
        validationReport: Stage1ResponseValidationReport,
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
