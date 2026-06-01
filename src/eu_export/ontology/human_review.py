"""Stage 1 human review package and report formatting."""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from eu_export.ontology.classification import (
    ProductClassificationInput,
    Stage1ClassificationResponseValidationReport,
    Stage1EvidencePackage,
    Stage1EvidenceRecord,
)
from eu_export.ontology.recommendation import (
    Stage1ClassificationRecommendationReport,
)
from eu_export.utils import NormalizeWhitespace


DEFAULT_HUMAN_REVIEW_TEXT_PREVIEW_CHARACTERS = 500


@dataclass(frozen=True)
class Stage1HumanReviewPackage:
    """Stage 1 결과를 사람이 검토할 수 있는 단일 패키지로 묶는다."""

    packageId: str
    selectedSource: str
    productFacts: Dict[str, Any]
    candidateGenerationProcess: Dict[str, Any]
    recommendationReport: Dict[str, Any]
    evidenceCitations: List[Dict[str, Any]] = field(default_factory=list)
    sourceEvidenceRecords: List[Dict[str, Any]] = field(default_factory=list)
    validationIssues: List[Dict[str, Any]] = field(default_factory=list)
    reviewChecklist: List[str] = field(default_factory=list)
    humanReviewWarning: str = (
        "This package is for human review and is not a final legal/customs "
        "determination."
    )
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "package_id": self.packageId,
            "selected_source": self.selectedSource,
            "product_facts": dict(self.productFacts),
            "candidate_generation_process": dict(self.candidateGenerationProcess),
            "recommendation_report": dict(self.recommendationReport),
            "evidence_citations": list(self.evidenceCitations),
            "source_evidence_records": list(self.sourceEvidenceRecords),
            "validation_issues": list(self.validationIssues),
            "review_checklist": list(self.reviewChecklist),
            "human_review_warning": self.humanReviewWarning,
            "limitations": list(self.limitations),
        }


class Stage1HumanReviewPackageBuilder:
    """후보 검토 요약/evidence/validation/product facts를 human review 단위로 결합한다."""

    def Build(
        self,
        productInput: ProductClassificationInput,
        recommendationReport: Stage1ClassificationRecommendationReport,
        validationReport: Stage1ClassificationResponseValidationReport,
        evidencePackage: Stage1EvidencePackage,
        selectedSource: str,
    ) -> Stage1HumanReviewPackage:
        recommendationData = recommendationReport.ToDict()
        evidenceRecordsById = {
            evidenceRecord.evidenceId: evidenceRecord
            for evidenceRecord in evidencePackage.evidenceRecords
        }
        citedEvidencePurposes = self.BuildCitationPurposeMap(recommendationData)
        systemRequiredEvidenceIds = self.BuildSystemRequiredCitationIds(
            validationReport,
        )
        citationOrigins = {
            evidenceId: (
                "system_required"
                if evidenceId in systemRequiredEvidenceIds
                else "llm_selected"
            )
            for evidenceId in citedEvidencePurposes
        }
        for groupName, purpose in [
            ("recommended_candidate", "priority_review_candidate_support"),
            ("retained_candidates", "comparison_candidate_review"),
            ("rejected_candidates_summary", "unlikely_candidate_basis"),
        ]:
            groupValue = recommendationData.get(groupName)
            candidateRecords = (
                [groupValue]
                if isinstance(groupValue, Mapping)
                else groupValue
            )
            if not isinstance(candidateRecords, list):
                continue
            for candidateRecord in candidateRecords:
                if not isinstance(candidateRecord, Mapping):
                    continue
                hs8 = candidateRecord.get("hs8")
                if not isinstance(hs8, str) or hs8 == "":
                    continue
                requiredEvidenceId = "cn_candidate:{0}".format(hs8)
                if requiredEvidenceId not in evidenceRecordsById:
                    continue
                citedEvidencePurposes[requiredEvidenceId] = self.MergeCitationPurpose(
                    citedEvidencePurposes.get(requiredEvidenceId),
                    purpose,
                )
                citationOrigins.setdefault(requiredEvidenceId, "system_required")

        return Stage1HumanReviewPackage(
            packageId=self.BuildPackageId(productInput, recommendationReport),
            selectedSource=selectedSource,
            productFacts=self.BuildProductFacts(productInput),
            candidateGenerationProcess=dict(
                recommendationData.get("candidate_generation_process", {}),
            ),
            recommendationReport=recommendationData,
            evidenceCitations=[
                self.BuildEvidenceCitation(
                    evidenceRecordsById[evidenceId],
                    purpose,
                    citationOrigins.get(evidenceId, "system_required"),
                )
                for evidenceId, purpose in citedEvidencePurposes.items()
                if evidenceId in evidenceRecordsById
            ],
            sourceEvidenceRecords=[
                self.BuildSourceEvidenceRecord(evidenceRecord)
                for evidenceRecord in evidencePackage.evidenceRecords
            ],
            validationIssues=[
                issue.ToDict() for issue in validationReport.issues
            ],
            reviewChecklist=self.BuildReviewChecklist(recommendationData),
            limitations=self.BuildLimitations(recommendationData),
        )

    def BuildPackageId(
        self,
        productInput: ProductClassificationInput,
        recommendationReport: Stage1ClassificationRecommendationReport,
    ) -> str:
        recommendedCandidate = recommendationReport.recommendedCandidate or {}
        recommendedHs8 = recommendedCandidate.get("hs8") or "unresolved"
        productName = NormalizeWhitespace(productInput.productName or "unknown")
        normalizedProductName = (
            "".join(
                character.lower()
                if character.isalnum()
                else "-"
                for character in productName
            )
            .strip("-")
        )
        return "stage1-human-review-{0}-{1}".format(
            normalizedProductName[:50] or "unknown",
            recommendedHs8,
        )

    def BuildProductFacts(
        self,
        productInput: ProductClassificationInput,
    ) -> Dict[str, Any]:
        return {
            **productInput.ToDict(),
            "notice_option_names": list(productInput.noticeOptionNames),
            "notice_field_texts": list(productInput.noticeFieldTexts),
            "product_notice_text_preview": self.BuildTextPreview(
                productInput.productNoticeText,
            ),
            "ocr_text_preview": self.BuildTextPreview(productInput.ocrText),
        }

    def BuildCitationPurposeMap(
        self,
        recommendationData: Mapping[str, Any],
    ) -> Dict[str, str]:
        citationPurposes: Dict[str, str] = {}
        for evidenceRef in recommendationData.get("key_evidence_refs", []):
            if isinstance(evidenceRef, str):
                citationPurposes[evidenceRef] = "decision_key_evidence"

        for groupName, purpose in [
            ("recommended_candidate", "priority_review_candidate_support"),
            ("retained_candidates", "comparison_candidate_review"),
            ("rejected_candidates_summary", "unlikely_candidate_basis"),
        ]:
            groupValue = recommendationData.get(groupName)
            candidateRecords = (
                [groupValue]
                if isinstance(groupValue, Mapping)
                else groupValue
            )
            if not isinstance(candidateRecords, list):
                continue
            for candidateRecord in candidateRecords:
                if not isinstance(candidateRecord, Mapping):
                    continue
                for evidenceRef in candidateRecord.get("evidence_refs", []):
                    if not isinstance(evidenceRef, str):
                        continue
                    citationPurposes[evidenceRef] = self.MergeCitationPurpose(
                        citationPurposes.get(evidenceRef),
                        purpose,
                    )
                similarEbtiCases = candidateRecord.get("similar_ebti_cases")
                if not isinstance(similarEbtiCases, list):
                    continue
                for similarEbtiCase in similarEbtiCases:
                    if not isinstance(similarEbtiCase, Mapping):
                        continue
                    evidenceRef = similarEbtiCase.get("evidence_ref")
                    if not isinstance(evidenceRef, str) or evidenceRef == "":
                        continue
                    citationPurposes[evidenceRef] = self.MergeCitationPurpose(
                        citationPurposes.get(evidenceRef),
                        "similar_ebti_comparison",
                    )
        return citationPurposes

    def BuildSystemRequiredCitationIds(
        self,
        validationReport: Stage1ClassificationResponseValidationReport,
    ) -> set[str]:
        classificationResult = validationReport.parsedResponse.get(
            "classification_result",
        )
        if not isinstance(classificationResult, Mapping):
            return set()
        candidateReviews = classificationResult.get("candidate_reviews")
        if not isinstance(candidateReviews, list):
            return set()

        evidenceIds: set[str] = set()
        for candidateReview in candidateReviews:
            if not isinstance(candidateReview, Mapping):
                continue
            systemRequiredEvidenceRefs = candidateReview.get(
                "system_required_evidence_refs",
            )
            if not isinstance(systemRequiredEvidenceRefs, list):
                continue
            for evidenceRef in systemRequiredEvidenceRefs:
                if isinstance(evidenceRef, str) and evidenceRef != "":
                    evidenceIds.add(evidenceRef)
        return evidenceIds

    def BuildEvidenceCitation(
        self,
        evidenceRecord: Stage1EvidenceRecord,
        purpose: str,
        citationOrigin: str,
    ) -> Dict[str, Any]:
        return {
            "evidence_id": evidenceRecord.evidenceId,
            "purpose": purpose,
            "citation_origin": citationOrigin,
            "evidence_type": evidenceRecord.evidenceType,
            "source_name": evidenceRecord.sourceName,
            "source_ref": evidenceRecord.sourceRef,
            "candidate_hs8": evidenceRecord.candidateHs8,
            "candidate_hs6": evidenceRecord.candidateHs6,
            "legal_status": evidenceRecord.legalStatus,
            "text": evidenceRecord.text,
            "text_preview": self.BuildTextPreview(evidenceRecord.text),
            "limitations": list(evidenceRecord.limitations),
        }

    def BuildSourceEvidenceRecord(
        self,
        evidenceRecord: Stage1EvidenceRecord,
    ) -> Dict[str, Any]:
        evidenceData = evidenceRecord.ToDict()
        evidenceData["text_preview"] = self.BuildTextPreview(evidenceRecord.text)
        return evidenceData

    def BuildReviewChecklist(
        self,
        recommendationData: Mapping[str, Any],
    ) -> List[str]:
        checklist = [
            "우선 검토 후보의 HS2-HS4-HS6-CN8 계층 검토 코멘트가 상품 정보와 모순되지 않는지 확인한다.",
            "우선 검토 CN8 후보가 상품 사실과 후보 카드의 hard condition을 동시에 만족하는지 확인한다.",
            "include/exclude rule 검토 코멘트가 상품고시정보와 OCR 근거를 적절히 반영했는지 확인한다.",
            "유사 EBTI 사례는 참고 근거일 뿐이므로 실제 상품과의 차이점을 별도로 확인한다.",
            "OCR 또는 상품고시정보에서 추출된 원재료/함량/용도 정보가 실제 상품 페이지와 일치하는지 확인한다.",
            "우선 검토 후보와 비교 검토 후보의 차이를 비교하고, 배제 가능 후보의 배제 사유가 충분한지 확인한다.",
            "이 패키지는 후보 산출 결과이며, 최종 법적/통관 판단으로 사용하지 않는다.",
        ]
        remainingRisks = recommendationData.get("remaining_risks")
        if isinstance(remainingRisks, list) and remainingRisks:
            checklist.append("remaining_risks 항목의 부족 정보가 해소되었는지 확인한다.")
        return checklist

    def BuildLimitations(
        self,
        recommendationData: Mapping[str, Any],
    ) -> List[str]:
        limitations = [
            limitation
            for limitation in recommendationData.get("limitations", [])
            if isinstance(limitation, str)
        ]
        limitations.append(
            "HumanReviewPackage는 검토 패키지이며 최종 법적/통관 판단이 아니다.",
        )
        return self.BuildUniqueStrings(limitations)

    def MergeCitationPurpose(
        self,
        currentPurpose: Optional[str],
        nextPurpose: str,
    ) -> str:
        if currentPurpose is None or currentPurpose == "":
            return nextPurpose
        if nextPurpose in currentPurpose.split(", "):
            return currentPurpose
        return "{0}, {1}".format(currentPurpose, nextPurpose)

    def BuildTextPreview(self, text: str) -> str:
        normalizedText = NormalizeWhitespace(text)
        if len(normalizedText) <= DEFAULT_HUMAN_REVIEW_TEXT_PREVIEW_CHARACTERS:
            return normalizedText
        return normalizedText[:DEFAULT_HUMAN_REVIEW_TEXT_PREVIEW_CHARACTERS].rstrip() + "..."

    def BuildUniqueStrings(self, values: Sequence[str]) -> List[str]:
        uniqueValues: List[str] = []
        seenValues: set[str] = set()
        for value in values:
            normalizedValue = NormalizeWhitespace(value)
            if normalizedValue == "" or normalizedValue in seenValues:
                continue
            seenValues.add(normalizedValue)
            uniqueValues.append(normalizedValue)
        return uniqueValues


class Stage1HumanReviewReportFormatter:
    """HumanReviewPackage를 GUI가 소비할 JSON 문자열로 출력한다."""

    def FormatJson(self, package: Stage1HumanReviewPackage) -> str:
        return json.dumps(package.ToDict(), ensure_ascii=False, indent=2)
