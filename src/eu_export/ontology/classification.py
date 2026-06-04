"""Ontology 기반 Stage 1 CN 후보 조회 helper."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from eu_export.bridge import (
    LlmGenerationOptions,
    LlmRequest,
    LlmResponse,
    LlmResponseFormat,
)
from eu_export.ontology.loader import OntologyDocumentLoader
from eu_export.ontology.schema import PackagedOntologyContext
from eu_export.utils import NormalizeWhitespace, NormalizeWhitespacePreservingLines


CN_LEAF_CODE_CARDS_DOCUMENT_ID = "table.cn_leaf_code_cards"
BTI_CASE_CHUNKS_DOCUMENT_ID = "table.bti_case_chunks"
FOOD_DOMAIN_SCOPE = "food_16_21"
COSMETICS_DOMAIN_SCOPE = "cosmetics_33"
DEFAULT_CN_CANDIDATE_TOP_K = 8
DEFAULT_STAGE1_BTI_EVIDENCE_PER_CANDIDATE = 3
DEFAULT_STAGE1_EVIDENCE_TEXT_MAX_CHARACTERS = 1400
DEFAULT_STAGE1_PROMPT_EVIDENCE_TEXT_MAX_CHARACTERS = 600
DEFAULT_STAGE1_PROMPT_COMMON_EVIDENCE_LIMIT = 6
DEFAULT_STAGE1_PROMPT_CANDIDATE_EVIDENCE_LIMIT = 3
DEFAULT_STAGE1_CLASSIFICATION_MAX_TOKENS = 4096
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
STAGE1_PROMPT_COMMON_EVIDENCE_TYPE_PRIORITY = [
    "product_fact",
    "product_notice_field",
    "product_notice_text",
    "ocr_text",
    "ontology_chunk",
]
STAGE1_PROMPT_CANDIDATE_EVIDENCE_TYPE_PRIORITY = [
    "bti_case_chunk",
    "cn_candidate_card",
]
STAGE1_CLASSIFICATION_ALLOWED_STATUSES = {
    "strong_candidate",
    "possible_candidate",
    "unlikely_candidate",
    "insufficient_information",
}
STAGE1_CLASSIFICATION_PATH_LEVELS = ["hs2", "hs4", "hs6", "cn8"]
STAGE1_CLASSIFICATION_PATH_ALLOWED_CONSISTENCIES = {
    "consistent",
    "conflicting",
    "needs_review",
}
FINAL_DETERMINATION_WARNING_TERMS = [
    "final determination",
    "definitive classification",
    "legally determined",
    "must be classified",
    "확정 코드",
    "최종 코드",
    "최종 분류",
    "법적 판단",
]
LOW_VALUE_MATCH_TERMS = {
    "animal",
    "blood",
    "containing",
    "cosmetic",
    "cosmetics",
    "crustaceans",
    "fish",
    "food",
    "insects",
    "meat",
    "molluscs",
    "offal",
    "other",
    "preparation",
    "preparations",
    "prepared",
    "preserved",
    "toilet",
    "weight",
}
PRODUCT_DOMAIN_SCOPE_MAP = {
    "food": [FOOD_DOMAIN_SCOPE],
    "cosmetics": [COSMETICS_DOMAIN_SCOPE],
    "ambiguous": [FOOD_DOMAIN_SCOPE, COSMETICS_DOMAIN_SCOPE],
    "unknown": [FOOD_DOMAIN_SCOPE, COSMETICS_DOMAIN_SCOPE],
}

TERM_EXPANSION_MAP = {
    "갈비": ["ribs", "cuts", "swine", "pork"],
    "고기": ["meat"],
    "돼지": ["pork", "swine", "domestic swine", "meat"],
    "돼지고기": ["pork", "swine", "domestic swine", "meat"],
    "쇠고기": ["beef", "meat"],
    "소고기": ["beef", "meat"],
    "닭": ["chicken", "meat"],
    "양념육": ["prepared meat", "preserved meat", "meat"],
    "생선": ["fish"],
    "어류": ["fish"],
    "새우": ["shrimp", "crustaceans"],
    "게": ["crab", "crustaceans"],
    "조개": ["molluscs"],
    "국수": ["noodle", "pasta"],
    "라면": ["noodle", "pasta"],
    "면류": ["noodle", "pasta"],
    "막국수": ["noodle", "buckwheat", "cereal"],
    "메밀": ["buckwheat", "cereal"],
    "소스": ["sauce"],
    "초콜릿": ["chocolate"],
    "캔디": ["sugar", "confectionery"],
    "클렌저": ["cleanser", "skin", "toilet preparation"],
    "세안": ["cleanser", "skin", "toilet preparation"],
    "샴푸": ["shampoo", "hair"],
    "립스틱": ["lip", "make-up"],
    "향수": ["perfume", "fragrance"],
    "치약": ["oral", "dental"],
    "화장품": ["cosmetic", "toilet preparation"],
}

STAGE1_CLASSIFICATION_SYSTEM_PROMPT = """\
You are an EU HS/CN classification review assistant for Korean exporters.
Use the supplied ontology context, normalized product facts, and CN candidate cards.
Do not issue a final legal/customs determination.
Review each candidate against the product facts and explain whether it is plausible.
Separate evidence, assumptions, missing information, and reasons to reject candidates.
Always keep human review required.
Return only a JSON object.
"""

STAGE1_CLASSIFICATION_JSON_INSTRUCTIONS = {
    "classification_result": {
        "product_name": "string",
        "product_domain": "food|cosmetics|ambiguous|unknown",
        "domain_scopes": ["string"],
        "candidate_reviews": [
            {
                "hs8": "string",
                "hs6_code": "string|null",
                "status": (
                    "strong_candidate|possible_candidate|unlikely_candidate|"
                    "insufficient_information"
                ),
                "supporting_product_facts": ["string"],
                "conflicting_or_exclusion_facts": ["string"],
                "missing_information": ["string"],
                "evidence_refs": ["string"],
                "classification_path_review": {
                    "hs2": {
                        "code": "string|null",
                        "consistency": "consistent|conflicting|needs_review",
                        "comment": "string",
                    },
                    "hs4": {
                        "code": "string|null",
                        "consistency": "consistent|conflicting|needs_review",
                        "comment": "string",
                    },
                    "hs6": {
                        "code": "string|null",
                        "consistency": "consistent|conflicting|needs_review",
                        "comment": "string",
                    },
                    "cn8": {
                        "code": "string|null",
                        "consistency": "consistent|conflicting|needs_review",
                        "comment": "string",
                    },
                },
                "classification_rule_review": {
                    "include_rule_comment": "string",
                    "exclude_rule_comment": "string",
                    "hard_condition_comment": "string",
                },
                "similar_ebti_cases": [
                    {
                        "evidence_ref": "string",
                        "similarity_comment": "string",
                        "difference_comment": "string",
                    }
                ],
                "reason": "string",
                "human_review_required": True,
            }
        ],
        "not_enough_information": ["string"],
        "recommended_next_action": "string",
        "human_review_warning": "string",
    }
}


@dataclass(frozen=True)
class ProductClassificationInput:
    """상품 수집 결과를 HS6/CN8 후보 조회에 맞게 정규화한 입력."""

    productPageUrl: Optional[str] = None
    productName: Optional[str] = None
    productDomain: str = "unknown"
    domainScopes: List[str] = field(default_factory=list)
    shortDescription: Optional[str] = None
    brandName: Optional[str] = None
    packageType: Optional[str] = None
    saleUnit: Optional[str] = None
    noticeFieldTexts: List[str] = field(default_factory=list)
    noticeOptionNames: List[str] = field(default_factory=list)
    productNoticeText: str = ""
    ocrText: str = ""

    def BuildSearchText(self) -> str:
        rawParts = [
            self.productName or "",
            self.shortDescription or "",
            self.brandName or "",
            self.packageType or "",
            self.saleUnit or "",
            *self.noticeOptionNames,
            *self.noticeFieldTexts,
            self.productNoticeText,
            self.ocrText,
        ]
        parts = [
            part
            for part in rawParts
            if isinstance(part, str) and part.strip() != ""
        ]
        return NormalizeWhitespacePreservingLines("\n".join(parts))

    def ToDict(self) -> Dict[str, Any]:
        return {
            "product_page_url": self.productPageUrl,
            "product_name": self.productName,
            "product_domain": self.productDomain,
            "domain_scopes": list(self.domainScopes),
            "short_description": self.shortDescription,
            "brand_name": self.brandName,
            "package_type": self.packageType,
            "sale_unit": self.saleUnit,
            "notice_field_texts": list(self.noticeFieldTexts),
            "notice_option_names": list(self.noticeOptionNames),
            "product_notice_text_length": len(self.productNoticeText),
            "ocr_text_length": len(self.ocrText),
            "search_text_length": len(self.BuildSearchText()),
        }


@dataclass(frozen=True)
class CnCandidate:
    """Stage 1에서 LLM/human review로 넘길 CN8 후보 카드."""

    hs8: str
    domainScope: str
    score: float
    matchedTerms: List[str] = field(default_factory=list)
    excludedTerms: List[str] = field(default_factory=list)
    includeRuleMatches: List[str] = field(default_factory=list)
    searchKeywordMatches: List[str] = field(default_factory=list)
    descriptionMatches: List[str] = field(default_factory=list)
    excludeRuleMatches: List[str] = field(default_factory=list)
    hs2Code: Optional[str] = None
    hs2Description: Optional[str] = None
    hs4Code: Optional[str] = None
    hs4Description: Optional[str] = None
    hs6Code: Optional[str] = None
    hs6Description: Optional[str] = None
    hs8Code: Optional[str] = None
    hs8Description: Optional[str] = None
    combinedDescription: str = ""
    includeRuleKeywords: str = ""
    excludeRuleKeywords: str = ""
    hardConditions: str = ""
    cnExplanatoryNote: str = ""
    needsHumanReview: bool = True

    def ToDict(self) -> Dict[str, Any]:
        return {
            "hs8": self.hs8,
            "domain_scope": self.domainScope,
            "score": self.score,
            "matched_terms": list(self.matchedTerms),
            "excluded_terms": list(self.excludedTerms),
            "include_rule_matches": list(self.includeRuleMatches),
            "search_keyword_matches": list(self.searchKeywordMatches),
            "description_matches": list(self.descriptionMatches),
            "exclude_rule_matches": list(self.excludeRuleMatches),
            "code_hierarchy": {
                "hs2": {
                    "code": self.hs2Code,
                    "description": self.hs2Description,
                },
                "hs4": {
                    "code": self.hs4Code,
                    "description": self.hs4Description,
                },
                "hs6": {
                    "code": self.hs6Code,
                    "description": self.hs6Description,
                },
                "cn8": {
                    "code": self.hs8Code or self.hs8,
                    "description": self.hs8Description,
                },
            },
            "score_breakdown": {
                "include_rule_points": 4.0 * len(self.includeRuleMatches),
                "search_keyword_points": 2.0 * len(self.searchKeywordMatches),
                "description_points": 1.0 * len(self.descriptionMatches),
                "exclude_rule_triggered": len(self.excludeRuleMatches) > 0,
                "formula": (
                    "include_rule_keywords*4 + search_keywords*2 + "
                    "description_matches*1; exclude_rule match forces score 0"
                ),
            },
            "combined_description": self.combinedDescription,
            "classification_rule_texts": {
                "include_rule_keywords": self.includeRuleKeywords,
                "exclude_rule_keywords": self.excludeRuleKeywords,
                "hard_conditions": self.hardConditions,
            },
            "cn_explanatory_note": self.cnExplanatoryNote,
            "needs_human_review": self.needsHumanReview,
        }

    def ToPromptDict(self) -> Dict[str, Any]:
        candidateData = self.ToDict()
        codeHierarchy = candidateData["code_hierarchy"]
        hierarchyPathParts: List[str] = []
        for level in ["hs2", "hs4", "hs6", "cn8"]:
            levelData = codeHierarchy.get(level)
            if not isinstance(levelData, Mapping):
                continue
            code = levelData.get("code")
            description = NormalizeWhitespace(str(levelData.get("description") or ""))
            if isinstance(code, str) and code.strip() and description:
                hierarchyPathParts.append("{0}: {1}".format(code, description))
            elif isinstance(code, str) and code.strip():
                hierarchyPathParts.append(code)
        return {
            "hs8": self.hs8,
            "hs6_code": self.hs6Code,
            "domain_scope": self.domainScope,
            "score": self.score,
            "code_hierarchy": codeHierarchy,
            "hierarchy_path_text": " > ".join(hierarchyPathParts),
            "classification_rule_texts": candidateData[
                "classification_rule_texts"
            ],
            "ranking_evidence": {
                "include_rule_matches": list(self.includeRuleMatches[:8]),
                "search_keyword_matches": list(self.searchKeywordMatches[:8]),
                "description_matches": list(self.descriptionMatches[:8]),
                "exclude_rule_matches": list(self.excludeRuleMatches[:8]),
            },
            "cn_explanatory_note": self.cnExplanatoryNote,
        }


@dataclass(frozen=True)
class Stage1EvidenceRecord:
    """Stage 1 후보 검토에서 LLM이 인용할 수 있는 단일 근거."""

    evidenceId: str
    evidenceType: str
    sourceName: str
    sourceRef: str
    text: str
    candidateHs8: Optional[str] = None
    candidateHs6: Optional[str] = None
    legalStatus: str = "internal_reference"
    limitations: List[str] = field(default_factory=list)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidenceId,
            "evidence_type": self.evidenceType,
            "source_name": self.sourceName,
            "source_ref": self.sourceRef,
            "text": self.text,
            "candidate_hs8": self.candidateHs8,
            "candidate_hs6": self.candidateHs6,
            "legal_status": self.legalStatus,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class Stage1EvidencePackage:
    """Stage 1 LLM request와 validator가 공유할 근거 묶음."""

    evidenceRecords: List[Stage1EvidenceRecord] = field(default_factory=list)
    commonEvidenceIds: List[str] = field(default_factory=list)
    candidateEvidenceIds: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def validEvidenceIds(self) -> Set[str]:
        return {
            evidenceRecord.evidenceId
            for evidenceRecord in self.evidenceRecords
        }

    def ToDict(self) -> Dict[str, Any]:
        return {
            "evidence_records": [
                evidenceRecord.ToDict()
                for evidenceRecord in self.evidenceRecords
            ],
            "common_evidence_ids": list(self.commonEvidenceIds),
            "candidate_evidence_ids": {
                candidateCode: list(evidenceIds)
                for candidateCode, evidenceIds in self.candidateEvidenceIds.items()
            },
        }

    def ToPromptDict(
        self,
        candidateCodes: Optional[Sequence[str]] = None,
        maxTextCharacters: int = DEFAULT_STAGE1_PROMPT_EVIDENCE_TEXT_MAX_CHARACTERS,
        commonEvidenceLimit: int = DEFAULT_STAGE1_PROMPT_COMMON_EVIDENCE_LIMIT,
        candidateEvidenceLimit: int = DEFAULT_STAGE1_PROMPT_CANDIDATE_EVIDENCE_LIMIT,
    ) -> Dict[str, Any]:
        def TrimText(text: str) -> str:
            if len(text) <= maxTextCharacters:
                return text
            return text[:maxTextCharacters].rstrip() + "..."

        def AppendSelectedId(selectedIds: List[str], evidenceId: str) -> None:
            if evidenceId not in selectedIds:
                selectedIds.append(evidenceId)

        def SelectByTypePriority(
            records: Sequence[Stage1EvidenceRecord],
            typePriority: Sequence[str],
            limit: int,
        ) -> List[str]:
            selectedIds: List[str] = []
            if limit <= 0:
                return selectedIds
            for evidenceType in typePriority:
                for record in records:
                    if len(selectedIds) >= limit:
                        return selectedIds
                    if record.evidenceType == evidenceType:
                        AppendSelectedId(selectedIds, record.evidenceId)
            for record in records:
                if len(selectedIds) >= limit:
                    return selectedIds
                AppendSelectedId(selectedIds, record.evidenceId)
            return selectedIds

        promptCandidateCodes = (
            list(candidateCodes)
            if candidateCodes is not None
            else list(self.candidateEvidenceIds.keys())
        )
        commonEvidenceIdSet = set(self.commonEvidenceIds)
        commonRecords = [
            evidenceRecord
            for evidenceRecord in self.evidenceRecords
            if evidenceRecord.evidenceId in commonEvidenceIdSet
        ]
        selectedCommonEvidenceIds = SelectByTypePriority(
            commonRecords,
            STAGE1_PROMPT_COMMON_EVIDENCE_TYPE_PRIORITY,
            commonEvidenceLimit,
        )
        selectedCandidateEvidenceIdsByCode: Dict[str, List[str]] = {}
        selectedEvidenceIds = list(selectedCommonEvidenceIds)

        for candidateCode in promptCandidateCodes:
            candidateEvidenceIdSet = set(
                self.candidateEvidenceIds.get(candidateCode, []),
            )
            candidateRecords = [
                evidenceRecord
                for evidenceRecord in self.evidenceRecords
                if evidenceRecord.candidateHs8 == candidateCode
                and evidenceRecord.evidenceId in candidateEvidenceIdSet
            ]
            selectedCandidateEvidenceIds = SelectByTypePriority(
                candidateRecords,
                STAGE1_PROMPT_CANDIDATE_EVIDENCE_TYPE_PRIORITY,
                candidateEvidenceLimit,
            )
            selectedCandidateEvidenceIdsByCode[candidateCode] = (
                selectedCandidateEvidenceIds
            )
            for evidenceId in selectedCandidateEvidenceIds:
                AppendSelectedId(selectedEvidenceIds, evidenceId)

        selectedEvidenceIdSet = set(selectedEvidenceIds)
        selectedEvidenceRecords = [
            evidenceRecord
            for evidenceRecord in self.evidenceRecords
            if evidenceRecord.evidenceId in selectedEvidenceIdSet
        ]

        def BuildPromptEvidenceRecord(
            evidenceRecord: Stage1EvidenceRecord,
        ) -> Dict[str, Any]:
            evidenceData = evidenceRecord.ToDict()
            evidenceText = evidenceRecord.text
            if evidenceRecord.evidenceType == "cn_candidate_card":
                evidenceText = (
                    "Candidate details are provided in "
                    "[stage1_cn_candidate_cards]. Use this evidence_id only "
                    "when citing the CN candidate card itself."
                )
            evidenceData["text"] = TrimText(evidenceText)
            return evidenceData

        return {
            "candidate_citation_requirements": [
                {
                    "hs8": candidateCode,
                    "must_include_one_of": list(selectedCandidateEvidenceIds),
                }
                for candidateCode, selectedCandidateEvidenceIds in (
                    selectedCandidateEvidenceIdsByCode.items()
                )
            ],
            "evidence_records": [
                BuildPromptEvidenceRecord(evidenceRecord)
                for evidenceRecord in selectedEvidenceRecords
            ],
            "common_evidence_ids": list(selectedCommonEvidenceIds),
            "candidate_evidence_ids": {
                candidateCode: [
                    *selectedCommonEvidenceIds,
                    *selectedCandidateEvidenceIds,
                ]
                for candidateCode, selectedCandidateEvidenceIds in (
                    selectedCandidateEvidenceIdsByCode.items()
                )
            },
            "valid_evidence_ids": sorted(selectedEvidenceIdSet),
            "omitted_evidence_record_count": (
                len(self.evidenceRecords) - len(selectedEvidenceRecords)
            ),
        }


class Stage1EvidencePackageBuilder:
    """Stage 1 후보 검토에 필요한 product/CN/ontology/BTI 근거를 묶는다."""

    def __init__(
        self,
        ontologyRootPath: str | Path,
        projectRootPath: Optional[str | Path] = None,
        maxBtiEvidencePerCandidate: int = DEFAULT_STAGE1_BTI_EVIDENCE_PER_CANDIDATE,
        maxEvidenceTextCharacters: int = DEFAULT_STAGE1_EVIDENCE_TEXT_MAX_CHARACTERS,
    ) -> None:
        self.ontologyRootPath = Path(ontologyRootPath)
        self.projectRootPath = (
            Path(projectRootPath)
            if projectRootPath is not None
            else self.ontologyRootPath.parent
        )
        self.maxBtiEvidencePerCandidate = max(0, maxBtiEvidencePerCandidate)
        self.maxEvidenceTextCharacters = max(200, maxEvidenceTextCharacters)

    def Build(
        self,
        productInput: ProductClassificationInput,
        candidates: Sequence[CnCandidate],
        packagedContext: Optional[PackagedOntologyContext] = None,
    ) -> Stage1EvidencePackage:
        evidenceRecords: List[Stage1EvidenceRecord] = []
        commonEvidenceIds: List[str] = []
        candidateEvidenceIds: Dict[str, List[str]] = {
            candidate.hs8: []
            for candidate in candidates
        }

        productEvidenceRecords = self._BuildProductEvidenceRecords(productInput)
        evidenceRecords.extend(productEvidenceRecords)
        commonEvidenceIds.extend(
            evidenceRecord.evidenceId
            for evidenceRecord in productEvidenceRecords
        )

        if packagedContext is not None:
            ontologyEvidenceRecords = self._BuildOntologyEvidenceRecords(
                packagedContext,
            )
            evidenceRecords.extend(ontologyEvidenceRecords)
            commonEvidenceIds.extend(
                evidenceRecord.evidenceId
                for evidenceRecord in ontologyEvidenceRecords
            )

        btiRowsByCandidate = self._BuildBtiRowsByCandidate(candidates)
        for candidate in candidates:
            candidateRecords = self._BuildCandidateEvidenceRecords(
                candidate,
                btiRowsByCandidate.get(candidate.hs8, []),
            )
            evidenceRecords.extend(candidateRecords)
            candidateEvidenceIds[candidate.hs8] = [
                *commonEvidenceIds,
                *[
                    evidenceRecord.evidenceId
                    for evidenceRecord in candidateRecords
                ],
            ]

        return Stage1EvidencePackage(
            evidenceRecords=evidenceRecords,
            commonEvidenceIds=commonEvidenceIds,
            candidateEvidenceIds=candidateEvidenceIds,
        )

    def _BuildProductEvidenceRecords(
        self,
        productInput: ProductClassificationInput,
    ) -> List[Stage1EvidenceRecord]:
        records: List[Stage1EvidenceRecord] = []
        productSummaryParts = [
            "product_name: {0}".format(productInput.productName or "unknown"),
            "product_domain: {0}".format(productInput.productDomain),
            "domain_scopes: {0}".format(", ".join(productInput.domainScopes)),
            "short_description: {0}".format(productInput.shortDescription or ""),
            "brand_name: {0}".format(productInput.brandName or ""),
            "package_type: {0}".format(productInput.packageType or ""),
            "sale_unit: {0}".format(productInput.saleUnit or ""),
        ]
        records.append(
            Stage1EvidenceRecord(
                evidenceId="product_fact:summary",
                evidenceType="product_fact",
                sourceName="product_classification_input",
                sourceRef=productInput.productPageUrl or "product_input",
                text=self._TrimEvidenceText("\n".join(productSummaryParts)),
                legalStatus="discovery",
                limitations=[
                    "Product facts are extracted inputs for review, not official classification evidence.",
                ],
            )
        )

        for index, noticeFieldText in enumerate(productInput.noticeFieldTexts, start=1):
            records.append(
                Stage1EvidenceRecord(
                    evidenceId="product_fact:notice_field:{0}".format(index),
                    evidenceType="product_notice_field",
                    sourceName="product_notice_information",
                    sourceRef=productInput.productPageUrl or "product_input",
                    text=self._TrimEvidenceText(noticeFieldText),
                    legalStatus="discovery",
                    limitations=[
                        "Product notice text may require human verification against the source page.",
                    ],
                )
            )

        if productInput.productNoticeText.strip():
            records.append(
                Stage1EvidenceRecord(
                    evidenceId="product_fact:notice_text",
                    evidenceType="product_notice_text",
                    sourceName="product_notice_information",
                    sourceRef=productInput.productPageUrl or "product_input",
                    text=self._TrimEvidenceText(productInput.productNoticeText),
                    legalStatus="discovery",
                    limitations=[
                        "Product notice text is source evidence for review, not final classification proof.",
                    ],
                )
            )

        if productInput.ocrText.strip():
            records.append(
                Stage1EvidenceRecord(
                    evidenceId="product_fact:ocr_text",
                    evidenceType="ocr_text",
                    sourceName="product_ocr_fallback",
                    sourceRef=productInput.productPageUrl or "product_input",
                    text=self._TrimEvidenceText(productInput.ocrText),
                    legalStatus="discovery",
                    limitations=[
                        "OCR text may contain recognition errors and must be reviewed.",
                    ],
                )
            )

        return records

    def _BuildOntologyEvidenceRecords(
        self,
        packagedContext: PackagedOntologyContext,
    ) -> List[Stage1EvidenceRecord]:
        records: List[Stage1EvidenceRecord] = []
        seenEvidenceIds: Set[str] = set()
        for selectedResult in packagedContext.selectedResults:
            chunk = selectedResult.chunk
            evidenceId = "ontology_chunk:{0}".format(chunk.chunkId)
            if evidenceId in seenEvidenceIds:
                continue
            seenEvidenceIds.add(evidenceId)
            records.append(
                Stage1EvidenceRecord(
                    evidenceId=evidenceId,
                    evidenceType="ontology_chunk",
                    sourceName=chunk.documentId,
                    sourceRef=chunk.relativePath,
                    text=self._TrimEvidenceText(chunk.ToContextText()),
                    legalStatus="internal_reference",
                    limitations=[
                        "Ontology chunk guides reasoning but does not replace official classification review.",
                    ],
                )
            )
        return records

    def _BuildCandidateEvidenceRecords(
        self,
        candidate: CnCandidate,
        btiRows: Sequence[Mapping[str, str]],
    ) -> List[Stage1EvidenceRecord]:
        records = [
            Stage1EvidenceRecord(
                evidenceId="cn_candidate:{0}".format(candidate.hs8),
                evidenceType="cn_candidate_card",
                sourceName="cn_leaf_code_cards",
                sourceRef=candidate.hs8,
                candidateHs8=candidate.hs8,
                candidateHs6=candidate.hs6Code,
                text=self._TrimEvidenceText(
                    json.dumps(
                        candidate.ToPromptDict(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
                legalStatus="internal_reference",
                limitations=[
                    "CN candidate card narrows review candidates and is not a final determination.",
                ],
            )
        ]

        for row in btiRows[: self.maxBtiEvidencePerCandidate]:
            chunkId = self._ReadString(row.get("chunk_id")) or "unknown"
            records.append(
                Stage1EvidenceRecord(
                    evidenceId="bti_case_chunk:{0}:{1}".format(
                        candidate.hs8,
                        chunkId,
                    ),
                    evidenceType="bti_case_chunk",
                    sourceName="bti_case_chunks",
                    sourceRef=self._ReadString(row.get("bti_reference")) or chunkId,
                    candidateHs8=candidate.hs8,
                    candidateHs6=candidate.hs6Code,
                    text=self._TrimEvidenceText(
                        self._ReadString(row.get("chunk_text")) or "",
                    ),
                    legalStatus="binding_to_holder",
                    limitations=[
                        "BTI is binding only for its holder and is used here as comparative evidence.",
                    ],
                )
            )

        return records

    def _BuildBtiRowsByCandidate(
        self,
        candidates: Sequence[CnCandidate],
    ) -> Dict[str, List[Mapping[str, str]]]:
        rowsByDomainScope = self._LoadBtiRowsByDomainScope()
        rowsByCandidate: Dict[str, List[Mapping[str, str]]] = {}
        for candidate in candidates:
            matchedRows: List[Mapping[str, str]] = []
            for row in rowsByDomainScope.get(candidate.domainScope, []):
                if not self._DoesBtiRowMatchCandidate(row, candidate):
                    continue
                matchedRows.append(row)
            rowsByCandidate[candidate.hs8] = sorted(
                matchedRows,
                key=self._BuildBtiRowSortKey,
            )[: self.maxBtiEvidencePerCandidate]
        return rowsByCandidate

    def _LoadBtiRowsByDomainScope(self) -> Dict[str, List[Dict[str, str]]]:
        rowsByDomainScope: Dict[str, List[Dict[str, str]]] = {}
        btiChunkDocument = self._FindDocument(BTI_CASE_CHUNKS_DOCUMENT_ID)
        if btiChunkDocument is None:
            return rowsByDomainScope

        for dataSource in self._ReadDataSources(btiChunkDocument):
            domainScope = self._ReadDomainScope(dataSource)
            resolvedPath = self._ResolvePath(str(dataSource.get("path", "")))
            if domainScope is None or resolvedPath is None:
                continue
            rowsByDomainScope[domainScope] = self._ReadCsvRows(resolvedPath)
        return rowsByDomainScope

    def _DoesBtiRowMatchCandidate(
        self,
        row: Mapping[str, str],
        candidate: CnCandidate,
    ) -> bool:
        candidateHs8 = self._NormalizeCode(candidate.hs8)
        candidateHs6 = self._NormalizeCode(candidate.hs6Code or "")
        rowCn8 = self._NormalizeCode(row.get("cn8", ""))
        rowAssignedCode = self._NormalizeCode(row.get("assigned_code", ""))
        rowHs6 = self._NormalizeCode(row.get("hs6", ""))
        chunkType = self._ReadString(row.get("chunk_type")) or ""
        needsReview = (self._ReadString(row.get("needs_review")) or "").lower()

        if chunkType != "case_summary":
            return False
        if needsReview in {"true", "1", "yes"}:
            return False
        if candidateHs8 and rowCn8 == candidateHs8:
            return True
        if candidateHs8 and rowAssignedCode.startswith(candidateHs8):
            return True
        return bool(candidateHs6 and rowHs6 == candidateHs6)

    def _BuildBtiRowSortKey(self, row: Mapping[str, str]) -> tuple[int, str]:
        priorityText = self._ReadString(row.get("chunk_priority")) or "9999"
        priority = int(priorityText) if priorityText.isdigit() else 9999
        return (priority, self._ReadString(row.get("chunk_id")) or "")

    def _FindDocument(self, documentId: str) -> Optional[Any]:
        documents = OntologyDocumentLoader(self.ontologyRootPath).LoadDocuments()
        for document in documents:
            if document.documentId == documentId:
                return document
        return None

    def _ReadDataSources(self, document: Any) -> List[Mapping[str, Any]]:
        dataSources = document.frontmatter.get("data_sources")
        if not isinstance(dataSources, list):
            return []
        return [
            dataSource
            for dataSource in dataSources
            if isinstance(dataSource, Mapping)
        ]

    def _ReadDomainScope(self, dataSource: Mapping[str, Any]) -> Optional[str]:
        resourceId = dataSource.get("resource_id")
        if not isinstance(resourceId, str):
            return None
        if resourceId.endswith("." + FOOD_DOMAIN_SCOPE):
            return FOOD_DOMAIN_SCOPE
        if resourceId.endswith("." + COSMETICS_DOMAIN_SCOPE):
            return COSMETICS_DOMAIN_SCOPE
        return None

    def _ResolvePath(self, declaredPath: str) -> Optional[Path]:
        if declaredPath == "":
            return None
        for candidatePath in [
            self.ontologyRootPath / declaredPath,
            self.projectRootPath / declaredPath,
        ]:
            if candidatePath.exists():
                return candidatePath
        return None

    def _ReadCsvRows(self, csvPath: Path) -> List[Dict[str, str]]:
        with csvPath.open("r", encoding="utf-8-sig", newline="") as csvFile:
            return [
                dict(row)
                for row in csv.DictReader(csvFile)
            ]

    def _TrimEvidenceText(self, text: str) -> str:
        normalizedText = NormalizeWhitespacePreservingLines(text)
        if len(normalizedText) <= self.maxEvidenceTextCharacters:
            return normalizedText
        return normalizedText[: self.maxEvidenceTextCharacters].rstrip() + "..."

    def _ReadString(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalizedValue = NormalizeWhitespace(value)
        return normalizedValue or None

    def _NormalizeCode(self, code: str) -> str:
        return "".join(character for character in code if character.isdigit())


class ProductClassificationInputNormalizer:
    """product pipeline 결과를 Stage 1 후보 조회 입력으로 변환한다."""

    def BuildFromKurlyPipelineResultData(
        self,
        pipelineResultData: Mapping[str, Any],
    ) -> ProductClassificationInput:
        if "parsed_product_page" in pipelineResultData:
            return self._BuildFromSlimKurlyPipelineResultData(pipelineResultData)
        if "collection_result" in pipelineResultData:
            return self._BuildFromCurrentKurlyPipelineResultData(pipelineResultData)
        if "product" in pipelineResultData and "notice" in pipelineResultData:
            return self._BuildFromCurrentKurlySmokeSummaryData(pipelineResultData)
        return self._BuildFromLegacyKurlySmokeResultData(pipelineResultData)

    def BuildFromKurlyPipelineResult(
        self,
        pipelineResult: Any,
    ) -> ProductClassificationInput:
        toDict = getattr(pipelineResult, "ToDict", None)
        if not callable(toDict):
            raise TypeError("pipelineResult must provide ToDict().")
        return self.BuildFromKurlyPipelineResultData(toDict())

    def _BuildFromSlimKurlyPipelineResultData(
        self,
        pipelineResultData: Mapping[str, Any],
    ) -> ProductClassificationInput:
        parsedProductPage = self._ReadMapping(
            pipelineResultData.get("parsed_product_page"),
        )
        return self._BuildInput(
            productPageUrl=self._ReadString(pipelineResultData.get("product_page_url")),
            parsedProductPage=parsedProductPage,
            combinedOcrText=self._ReadString(
                pipelineResultData.get("combined_ocr_text"),
            )
            or "",
        )

    def _BuildFromCurrentKurlyPipelineResultData(
        self,
        pipelineResultData: Mapping[str, Any],
    ) -> ProductClassificationInput:
        collectionResult = self._ReadMapping(
            pipelineResultData.get("collection_result"),
        )
        parsedProductPage = self._ReadMapping(
            collectionResult.get("parsed_product_page"),
        )
        return self._BuildInput(
            productPageUrl=self._ReadString(collectionResult.get("product_page_url")),
            parsedProductPage=parsedProductPage,
            combinedOcrText=self._ReadString(
                pipelineResultData.get("combined_ocr_text"),
            )
            or "",
        )

    def _BuildFromLegacyKurlySmokeResultData(
        self,
        smokeResultData: Mapping[str, Any],
    ) -> ProductClassificationInput:
        return self._BuildInput(
            productPageUrl=self._ReadString(smokeResultData.get("product_page_url")),
            parsedProductPage=smokeResultData,
            combinedOcrText=self._BuildCombinedOcrTextFromResultData(smokeResultData),
        )

    def _BuildFromCurrentKurlySmokeSummaryData(
        self,
        smokeResultData: Mapping[str, Any],
    ) -> ProductClassificationInput:
        productData = self._ReadMapping(smokeResultData.get("product"))
        noticeData = self._ReadMapping(smokeResultData.get("notice"))
        ocrData = self._ReadMapping(smokeResultData.get("ocr"))
        parsedProductPage = {
            "product_name": productData.get("product_name"),
            "product_domain": productData.get("product_domain"),
            "short_description": productData.get("short_description"),
            "brand_name": productData.get("brand_name"),
            "package_type": productData.get("package_type"),
            "sale_unit": productData.get("sale_unit"),
            "product_notice_option_names": noticeData.get("option_names"),
            "product_notice_fields": noticeData.get("fields_preview"),
            "product_notice_options": noticeData.get("options_preview"),
        }
        return self._BuildInput(
            productPageUrl=self._ReadString(smokeResultData.get("product_page_url")),
            parsedProductPage=parsedProductPage,
            combinedOcrText=self._ReadString(
                ocrData.get("combined_text_preview"),
            )
            or "",
        )

    def _BuildInput(
        self,
        productPageUrl: Optional[str],
        parsedProductPage: Mapping[str, Any],
        combinedOcrText: str,
    ) -> ProductClassificationInput:
        productDomain = self._ReadString(
            parsedProductPage.get("product_domain"),
        ) or "unknown"
        noticeFields = self._ReadMappingList(
            parsedProductPage.get("product_notice_fields"),
        )
        noticeOptions = self._ReadMappingList(
            parsedProductPage.get("product_notice_options"),
        )
        productNoticeText = self._ReadString(
            parsedProductPage.get("raw_product_notice_text"),
        ) or self._BuildRawNoticeText(noticeFields, noticeOptions)
        noticeOptionNames = self._ReadStringList(
            parsedProductPage.get("product_notice_option_names"),
        )
        if not noticeOptionNames:
            noticeOptionNames = self._ExtractNoticeOptionNames(noticeOptions)

        return ProductClassificationInput(
            productPageUrl=productPageUrl,
            productName=self._ReadString(parsedProductPage.get("product_name")),
            productDomain=productDomain,
            domainScopes=self._BuildDomainScopes(productDomain),
            shortDescription=self._ReadString(
                parsedProductPage.get("short_description"),
            ),
            brandName=self._ReadString(parsedProductPage.get("brand_name")),
            packageType=self._ReadString(parsedProductPage.get("package_type")),
            saleUnit=self._ReadString(parsedProductPage.get("sale_unit")),
            noticeFieldTexts=self._BuildNoticeFieldTexts(noticeFields),
            noticeOptionNames=noticeOptionNames,
            productNoticeText=productNoticeText,
            ocrText=combinedOcrText,
        )

    def _BuildNoticeFieldTexts(
        self,
        noticeFields: Sequence[Mapping[str, Any]],
    ) -> List[str]:
        fieldTexts: List[str] = []
        for noticeField in noticeFields:
            fieldName = self._ReadString(noticeField.get("field_name"))
            fieldValue = self._ReadString(noticeField.get("field_value"))
            if fieldName is None and fieldValue is None:
                continue
            if fieldName is None:
                fieldTexts.append(fieldValue or "")
                continue
            if fieldValue is None:
                fieldTexts.append(fieldName)
                continue
            fieldTexts.append("{0}: {1}".format(fieldName, fieldValue))
        return fieldTexts

    def _BuildRawNoticeText(
        self,
        noticeFields: Sequence[Mapping[str, Any]],
        noticeOptions: Sequence[Mapping[str, Any]],
    ) -> str:
        rawTexts: List[str] = []
        for noticeOption in noticeOptions:
            rawText = self._ReadString(noticeOption.get("raw_text"))
            if rawText is not None:
                rawTexts.append(rawText)
                continue
            optionName = self._ReadString(noticeOption.get("option_name"))
            optionFields = self._ReadMappingList(noticeOption.get("fields"))
            if optionName is not None:
                rawTexts.append(optionName)
            rawTexts.extend(self._BuildNoticeFieldTexts(optionFields))
        if not rawTexts:
            rawTexts = [
                rawText
                for rawText in (
                    self._ReadString(noticeField.get("raw_text"))
                    for noticeField in noticeFields
                )
                if rawText is not None
            ]
        if not rawTexts:
            rawTexts = self._BuildNoticeFieldTexts(noticeFields)
        return NormalizeWhitespacePreservingLines("\n".join(rawTexts))

    def _ExtractNoticeOptionNames(
        self,
        noticeOptions: Sequence[Mapping[str, Any]],
    ) -> List[str]:
        optionNames: List[str] = []
        seenOptionNames: Set[str] = set()
        for noticeOption in noticeOptions:
            optionName = self._ReadString(noticeOption.get("option_name"))
            if optionName is None or optionName in seenOptionNames:
                continue
            seenOptionNames.add(optionName)
            optionNames.append(optionName)
        return optionNames

    def _BuildDomainScopes(self, productDomain: str) -> List[str]:
        normalizedProductDomain = NormalizeWhitespace(productDomain).lower()
        return list(
            PRODUCT_DOMAIN_SCOPE_MAP.get(
                normalizedProductDomain,
                PRODUCT_DOMAIN_SCOPE_MAP["unknown"],
            )
        )

    def _BuildCombinedOcrTextFromResultData(
        self,
        resultData: Mapping[str, Any],
    ) -> str:
        directOcrText = self._ReadString(resultData.get("combined_ocr_text"))
        if directOcrText is not None:
            return directOcrText

        ocrImageResults = self._ReadMappingList(resultData.get("ocr_image_results"))
        return NormalizeWhitespacePreservingLines(
            "\n".join(
                ocrText
                for ocrText in (
                    self._ReadString(imageResult.get("ocr_text"))
                    for imageResult in ocrImageResults
                )
                if ocrText is not None
            )
        )

    def _ReadString(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalizedValue = NormalizeWhitespacePreservingLines(value)
        return normalizedValue or None

    def _ReadStringList(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        values: List[str] = []
        for item in value:
            normalizedItem = self._ReadString(item)
            if normalizedItem is not None:
                values.append(normalizedItem)
        return values

    def _ReadMapping(self, value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        return {}

    def _ReadMappingList(self, value: Any) -> List[Mapping[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, Mapping)]


class CnCandidateRetriever:
    """CN leaf card CSV를 이용해 product profile과 가까운 CN8 후보를 찾는다."""

    def __init__(
        self,
        ontologyRootPath: str | Path,
        projectRootPath: Optional[str | Path] = None,
    ) -> None:
        self.ontologyRootPath = Path(ontologyRootPath)
        self.projectRootPath = (
            Path(projectRootPath)
            if projectRootPath is not None
            else self.ontologyRootPath.parent
        )
        self._rowsByDomainScope: Optional[Dict[str, List[Dict[str, str]]]] = None

    def FindCandidates(
        self,
        productInput: ProductClassificationInput,
        topK: int = DEFAULT_CN_CANDIDATE_TOP_K,
    ) -> List[CnCandidate]:
        rowsByDomainScope = self._LoadRowsByDomainScope()
        searchText = productInput.BuildSearchText()
        searchTerms = self._BuildExpandedSearchTerms(searchText)
        candidates: List[CnCandidate] = []

        for domainScope in productInput.domainScopes:
            for row in rowsByDomainScope.get(domainScope, []):
                candidate = self._ScoreRow(
                    row=row,
                    domainScope=domainScope,
                    searchText=searchText,
                    searchTerms=searchTerms,
                )
                if candidate.score > 0:
                    candidates.append(candidate)

        return sorted(
            candidates,
            key=lambda candidate: (
                -candidate.score,
                candidate.domainScope,
                candidate.hs8,
            ),
        )[: max(0, topK)]

    def FindSiblingCandidates(
        self,
        productInput: ProductClassificationInput,
        currentCandidates: Sequence[CnCandidate],
        excludedHs8Codes: Sequence[str],
        topK: int = DEFAULT_CN_CANDIDATE_TOP_K,
    ) -> List[CnCandidate]:
        rowsByDomainScope = self._LoadRowsByDomainScope()
        searchText = productInput.BuildSearchText()
        searchTerms = self._BuildExpandedSearchTerms(searchText)
        excludedHs8CodeSet = set(excludedHs8Codes)
        parentHs6CodesByDomainScope: Dict[str, Set[str]] = {}

        for candidate in currentCandidates:
            if candidate.hs6Code is None:
                continue
            parentHs6CodesByDomainScope.setdefault(
                candidate.domainScope,
                set(),
            ).add(candidate.hs6Code)

        siblingCandidates: List[CnCandidate] = []
        for domainScope in productInput.domainScopes:
            parentHs6Codes = parentHs6CodesByDomainScope.get(domainScope, set())
            for row in rowsByDomainScope.get(domainScope, []):
                hs8 = row.get("hs8", "")
                hs6 = row.get("hs6_code", "")
                if hs8 in excludedHs8CodeSet:
                    continue
                if parentHs6Codes and hs6 not in parentHs6Codes:
                    continue
                candidate = self._ScoreRow(
                    row=row,
                    domainScope=domainScope,
                    searchText=searchText,
                    searchTerms=searchTerms,
                )
                if candidate.score <= 0:
                    continue
                siblingCandidates.append(candidate)

        return sorted(
            siblingCandidates,
            key=lambda candidate: (
                -candidate.score,
                candidate.domainScope,
                candidate.hs8,
            ),
        )[: max(0, topK)]

    def _ScoreRow(
        self,
        row: Mapping[str, str],
        domainScope: str,
        searchText: str,
        searchTerms: Set[str],
    ) -> CnCandidate:
        matchedTerms: Set[str] = set()
        excludedTerms: Set[str] = set()
        score = 0.0

        includeMatches = self._FindCellMatches(
            row.get("include_rule_keywords", ""),
            searchText,
            searchTerms,
        )
        searchKeywordMatches = self._FindCellMatches(
            row.get("search_keywords", ""),
            searchText,
            searchTerms,
        )
        descriptionMatches = self._FindTokenMatches(
            " ".join(
                [
                    row.get("combined_description", ""),
                    row.get("cn_explanatory_note", ""),
                    row.get("hs8_description", ""),
                ]
            ),
            searchTerms,
        )
        excludeMatches = self._FindCellMatches(
            row.get("exclude_rule_keywords", ""),
            searchText,
            searchTerms,
        )

        matchedTerms.update(includeMatches)
        matchedTerms.update(searchKeywordMatches)
        matchedTerms.update(descriptionMatches)
        excludedTerms.update(excludeMatches)

        if excludeMatches:
            return self._BuildCandidate(
                row=row,
                domainScope=domainScope,
                score=0.0,
                matchedTerms=sorted(matchedTerms),
                excludedTerms=sorted(excludedTerms),
                includeRuleMatches=includeMatches,
                searchKeywordMatches=searchKeywordMatches,
                descriptionMatches=descriptionMatches,
                excludeRuleMatches=excludeMatches,
            )

        score += 4.0 * len(includeMatches)
        score += 2.0 * len(searchKeywordMatches)
        score += 1.0 * len(descriptionMatches)

        if score < 0:
            score = 0.0

        return self._BuildCandidate(
            row=row,
            domainScope=domainScope,
            score=score,
            matchedTerms=sorted(matchedTerms),
            excludedTerms=sorted(excludedTerms),
            includeRuleMatches=includeMatches,
            searchKeywordMatches=searchKeywordMatches,
            descriptionMatches=descriptionMatches,
            excludeRuleMatches=excludeMatches,
        )

    def _BuildCandidate(
        self,
        row: Mapping[str, str],
        domainScope: str,
        score: float,
        matchedTerms: Sequence[str],
        excludedTerms: Sequence[str],
        includeRuleMatches: Sequence[str],
        searchKeywordMatches: Sequence[str],
        descriptionMatches: Sequence[str],
        excludeRuleMatches: Sequence[str],
    ) -> CnCandidate:
        return CnCandidate(
            hs8=row.get("hs8", ""),
            domainScope=domainScope,
            score=round(score, 3),
            matchedTerms=list(matchedTerms),
            excludedTerms=list(excludedTerms),
            includeRuleMatches=list(includeRuleMatches),
            searchKeywordMatches=list(searchKeywordMatches),
            descriptionMatches=list(descriptionMatches),
            excludeRuleMatches=list(excludeRuleMatches),
            hs2Code=row.get("hs2_code") or None,
            hs2Description=row.get("hs2_description") or None,
            hs4Code=row.get("hs4_code") or None,
            hs4Description=row.get("hs4_description") or None,
            hs6Code=row.get("hs6_code") or None,
            hs6Description=row.get("hs6_description") or None,
            hs8Code=row.get("hs8_code") or row.get("hs8") or None,
            hs8Description=row.get("hs8_description") or None,
            combinedDescription=row.get("combined_description", ""),
            includeRuleKeywords=row.get("include_rule_keywords", ""),
            excludeRuleKeywords=row.get("exclude_rule_keywords", ""),
            hardConditions=row.get("hard_conditions", ""),
            cnExplanatoryNote=row.get("cn_explanatory_note", ""),
            needsHumanReview=True,
        )

    def _LoadRowsByDomainScope(self) -> Dict[str, List[Dict[str, str]]]:
        if self._rowsByDomainScope is not None:
            return self._rowsByDomainScope

        rowsByDomainScope: Dict[str, List[Dict[str, str]]] = {}
        leafCardDocument = self._FindLeafCardDocument()
        if leafCardDocument is None:
            self._rowsByDomainScope = rowsByDomainScope
            return rowsByDomainScope

        for dataSource in self._ReadDataSources(leafCardDocument):
            domainScope = self._ReadDomainScope(dataSource)
            resolvedPath = self._ResolvePath(str(dataSource.get("path", "")))
            if domainScope is None or resolvedPath is None:
                continue
            rowsByDomainScope[domainScope] = self._ReadCsvRows(resolvedPath)

        self._rowsByDomainScope = rowsByDomainScope
        return rowsByDomainScope

    def _FindLeafCardDocument(self) -> Optional[Any]:
        documents = OntologyDocumentLoader(self.ontologyRootPath).LoadDocuments()
        for document in documents:
            if document.documentId == CN_LEAF_CODE_CARDS_DOCUMENT_ID:
                return document
        return None

    def _ReadDataSources(self, document: Any) -> List[Mapping[str, Any]]:
        dataSources = document.frontmatter.get("data_sources")
        if not isinstance(dataSources, list):
            return []
        return [
            dataSource
            for dataSource in dataSources
            if isinstance(dataSource, Mapping)
        ]

    def _ReadDomainScope(self, dataSource: Mapping[str, Any]) -> Optional[str]:
        resourceId = dataSource.get("resource_id")
        if not isinstance(resourceId, str):
            return None
        if resourceId.endswith("." + FOOD_DOMAIN_SCOPE):
            return FOOD_DOMAIN_SCOPE
        if resourceId.endswith("." + COSMETICS_DOMAIN_SCOPE):
            return COSMETICS_DOMAIN_SCOPE
        return None

    def _ResolvePath(self, declaredPath: str) -> Optional[Path]:
        if declaredPath == "":
            return None
        for candidatePath in [
            self.ontologyRootPath / declaredPath,
            self.projectRootPath / declaredPath,
        ]:
            if candidatePath.exists():
                return candidatePath
        return None

    def _ReadCsvRows(self, csvPath: Path) -> List[Dict[str, str]]:
        with csvPath.open("r", encoding="utf-8-sig", newline="") as csvFile:
            return [
                dict(row)
                for row in csv.DictReader(csvFile)
            ]

    def _BuildExpandedSearchTerms(self, searchText: str) -> Set[str]:
        terms = set(self._ExtractTerms(searchText))
        loweredSearchText = searchText.lower()
        for sourceTerm, expandedTerms in TERM_EXPANSION_MAP.items():
            if sourceTerm.lower() not in loweredSearchText:
                continue
            for expandedTerm in expandedTerms:
                terms.update(self._ExtractTerms(expandedTerm))
        return terms

    def _FindCellMatches(
        self,
        cellValue: str,
        searchText: str,
        searchTerms: Set[str],
    ) -> List[str]:
        matchedTerms: List[str] = []
        normalizedSearchText = searchText.lower()
        for phrase in self._SplitKeywordCell(cellValue):
            phraseTerms = [
                term
                for term in self._ExtractTerms(phrase)
                if self._IsMatchableTerm(term)
            ]
            if not phraseTerms:
                continue
            normalizedPhrase = NormalizeWhitespace(phrase).lower()
            if normalizedPhrase and normalizedPhrase in normalizedSearchText:
                matchedTerms.append(normalizedPhrase)
                continue
            if all(term in searchTerms for term in phraseTerms):
                matchedTerms.append(normalizedPhrase)
        return sorted(set(matchedTerms))

    def _FindTokenMatches(self, text: str, searchTerms: Set[str]) -> List[str]:
        return sorted(
            term
            for term in set(self._ExtractTerms(text)).intersection(searchTerms)
            if self._IsMatchableTerm(term)
        )

    def _SplitKeywordCell(self, cellValue: str) -> List[str]:
        values: List[str] = []
        for rawPart in re.split(r"[;\n]", cellValue or ""):
            value = NormalizeWhitespace(rawPart).lower()
            if value:
                values.append(value)
        return values

    def _ExtractTerms(self, text: str) -> List[str]:
        return [
            token.lower()
            for token in TOKEN_PATTERN.findall(text or "")
            if len(token) >= 2 and not token.isdigit()
        ]

    def _IsMatchableTerm(self, term: str) -> bool:
        return term not in LOW_VALUE_MATCH_TERMS and not term.isdigit()


class Stage1RequestBuilder:
    """ProductClassificationInput과 CN 후보를 LLM 검토 요청으로 묶는다."""

    def __init__(
        self,
        systemPrompt: str = STAGE1_CLASSIFICATION_SYSTEM_PROMPT,
    ) -> None:
        self.systemPrompt = systemPrompt.strip()

    def BuildRequest(
        self,
        productInput: ProductClassificationInput,
        candidates: Sequence[CnCandidate],
        packagedContext: PackagedOntologyContext,
        evidencePackage: Optional[Stage1EvidencePackage] = None,
        userPrompt: Optional[str] = None,
        maxCandidateCount: int = DEFAULT_CN_CANDIDATE_TOP_K,
    ) -> LlmRequest:
        promptCandidates = candidates[:maxCandidateCount]
        if not promptCandidates:
            raise ValueError(
                (
                    "Stage 1 classification request requires at least one CN "
                    "candidate. Stop before LLM request generation when candidate "
                    "retrieval returns no candidates."
                )
            )
        contextChunks = [
            self._BuildProductContextChunk(productInput),
            self._BuildCandidateContextChunk(promptCandidates),
        ]
        if evidencePackage is not None:
            contextChunks.append(
                self._BuildEvidencePackageContextChunk(
                    evidencePackage,
                    promptCandidates,
                )
            )
        else:
            contextChunks.extend(packagedContext.contextChunks)
        return LlmRequest(
            userPrompt=userPrompt
            or self._BuildDefaultUserPrompt(
                productInput,
                hasEvidencePackage=evidencePackage is not None,
            ),
            systemPrompt=self.systemPrompt,
            contextChunks=contextChunks,
            responseFormat=LlmResponseFormat.JSON_OBJECT,
            generationOptions=LlmGenerationOptions(
                temperature=0.0,
                maxTokens=DEFAULT_STAGE1_CLASSIFICATION_MAX_TOKENS,
            ),
        )

    def BuildOntologyQuery(
        self,
        productInput: ProductClassificationInput,
        candidates: Sequence[CnCandidate],
    ) -> str:
        candidateCodes = " ".join(candidate.hs8 for candidate in candidates)
        candidateHs6Codes = " ".join(
            candidate.hs6Code or ""
            for candidate in candidates
            if candidate.hs6Code is not None
        )
        return NormalizeWhitespace(
            " ".join(
                [
                    "stage1_classification HS6 CN8 candidate review",
                    productInput.productDomain,
                    " ".join(productInput.domainScopes),
                    productInput.productName or "",
                    candidateCodes,
                    candidateHs6Codes,
                    "cn_leaf_code_cards classification evidence human review",
                ]
            )
        )

    def _BuildProductContextChunk(
        self,
        productInput: ProductClassificationInput,
    ) -> str:
        productData = productInput.ToDict()
        productData["product_notice_text"] = productInput.productNoticeText
        productData["ocr_text"] = productInput.ocrText
        return "\n".join(
            [
                "[stage1_product_classification_input]",
                json.dumps(
                    productData,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ]
        )

    def _BuildCandidateContextChunk(
        self,
        candidates: Sequence[CnCandidate],
    ) -> str:
        return "\n".join(
            [
                "[stage1_cn_candidate_cards]",
                json.dumps(
                    [candidate.ToPromptDict() for candidate in candidates],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ]
        )

    def _BuildEvidencePackageContextChunk(
        self,
        evidencePackage: Stage1EvidencePackage,
        candidates: Sequence[CnCandidate],
    ) -> str:
        return "\n".join(
            [
                "[stage1_evidence_package]",
                "Use only evidence_id values from this package when returning evidence_refs.",
                (
                    "For every candidate_review status, cite at least one "
                    "evidence_id from candidate_citation_requirements.must_include_one_of "
                    "for the reviewed hs8."
                ),
                json.dumps(
                    evidencePackage.ToPromptDict(
                        candidateCodes=[candidate.hs8 for candidate in candidates],
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ]
        )

    def _BuildDefaultUserPrompt(
        self,
        productInput: ProductClassificationInput,
        hasEvidencePackage: bool,
    ) -> str:
        instructions = json.dumps(
            STAGE1_CLASSIFICATION_JSON_INSTRUCTIONS,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        evidenceInstructions = [
            (
                "evidence_refs에는 제공된 stage1_evidence_package의 "
                "evidence_id만 사용하라."
            ),
            (
                "모든 candidate_review는 상태와 무관하게 reviewed hs8과 "
                "candidate_hs8이 같은 후보 전용 evidence를 최소 1개 인용하라."
            ),
        ] if hasEvidencePackage else [
            (
                "stage1_evidence_package가 제공되지 않은 경우 evidence_refs는 "
                "빈 배열로 두고, 제공된 product facts와 context를 기준으로 "
                "reason을 작성하라."
            ),
        ]
        return "\n".join(
            [
                "아래 product facts와 CN candidate cards를 검토해 Stage 1 HS6/CN8 후보 검토 JSON을 작성하라.",
                "최종 법적/통관 판단으로 표현하지 말고, 후보별 가능성·배제 근거·부족 정보를 구분하라.",
                "각 후보의 code_hierarchy를 사용해 HS2, HS4, HS6, CN8 단계가 상품 정보와 논리적으로 이어지는지 검토하라.",
                "classification_rule_texts의 include_rule_keywords, exclude_rule_keywords, hard_conditions를 후보별 판단 근거로 검토하라.",
                "유사 EBTI 사례가 제공된 경우 similar_ebti_cases에 유사점과 차이점을 구분해 작성하라.",
                *evidenceInstructions,
                "상품명: {0}".format(productInput.productName or "unknown"),
                "응답 JSON 구조:",
                instructions,
            ]
        )


@dataclass(frozen=True)
class Stage1ResponseValidationIssue:
    """Stage 1 LLM 응답 구조 검증 결과의 단일 이슈."""

    severity: str
    issueCode: str
    fieldPath: str
    message: str

    def ToDict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "issue_code": self.issueCode,
            "field_path": self.fieldPath,
            "message": self.message,
        }


@dataclass(frozen=True)
class Stage1ResponseValidationReport:
    """Stage 1 LLM 응답이 후보 검토 JSON 계약을 만족하는지 나타낸다."""

    isValid: bool
    parsedResponse: Dict[str, Any] = field(default_factory=dict)
    issues: List[Stage1ResponseValidationIssue] = field(
        default_factory=list,
    )

    def ToDict(self) -> Dict[str, Any]:
        errorCount = sum(1 for issue in self.issues if issue.severity == "error")
        warningCount = sum(
            1
            for issue in self.issues
            if issue.severity == "warning"
        )
        return {
            "is_valid": self.isValid,
            "error_count": errorCount,
            "warning_count": warningCount,
            "issues": [issue.ToDict() for issue in self.issues],
            "parsed_response": dict(self.parsedResponse),
        }


class Stage1ResponseValidator:
    """LLM의 Stage 1 후보 검토 JSON 응답을 구조적으로 검증한다."""

    def ValidateResponse(
        self,
        llmResponse: LlmResponse,
        productInput: ProductClassificationInput,
        candidates: Sequence[CnCandidate],
        evidencePackage: Optional[Stage1EvidencePackage] = None,
    ) -> Stage1ResponseValidationReport:
        return self.ValidateText(
            llmResponse.generatedText,
            productInput,
            candidates,
            evidencePackage=evidencePackage,
        )

    def ValidateText(
        self,
        responseText: str,
        productInput: ProductClassificationInput,
        candidates: Sequence[CnCandidate],
        evidencePackage: Optional[Stage1EvidencePackage] = None,
    ) -> Stage1ResponseValidationReport:
        issues: List[Stage1ResponseValidationIssue] = []
        parsedResponse = self._ParseResponseText(responseText, issues)
        if parsedResponse is None:
            return Stage1ResponseValidationReport(
                isValid=False,
                parsedResponse={},
                issues=issues,
            )

        if evidencePackage is not None:
            self._AttachRequiredCandidateEvidenceRefs(
                parsedResponse,
                candidates,
                evidencePackage,
            )

        self._ValidateClassificationResult(
            parsedResponse,
            productInput,
            candidates,
            evidencePackage,
            issues,
        )
        self._DetectFinalDeterminationLanguage(responseText, issues)

        return Stage1ResponseValidationReport(
            isValid=not any(issue.severity == "error" for issue in issues),
            parsedResponse=parsedResponse,
            issues=issues,
        )

    def _AttachRequiredCandidateEvidenceRefs(
        self,
        parsedResponse: Dict[str, Any],
        candidates: Sequence[CnCandidate],
        evidencePackage: Stage1EvidencePackage,
    ) -> None:
        classificationResult = parsedResponse.get("classification_result")
        if not isinstance(classificationResult, dict):
            return
        candidateReviews = classificationResult.get("candidate_reviews")
        if not isinstance(candidateReviews, list):
            return

        expectedHs8Codes = {candidate.hs8 for candidate in candidates}
        validEvidenceIds = evidencePackage.validEvidenceIds
        for candidateReview in candidateReviews:
            if not isinstance(candidateReview, dict):
                continue
            hs8 = candidateReview.get("hs8")
            if not isinstance(hs8, str) or hs8 not in expectedHs8Codes:
                continue
            requiredEvidenceId = "cn_candidate:{0}".format(hs8)
            if requiredEvidenceId not in validEvidenceIds:
                continue
            if requiredEvidenceId not in evidencePackage.candidateEvidenceIds.get(
                hs8,
                [],
            ):
                continue

            systemRequiredEvidenceRefs = candidateReview.get(
                "system_required_evidence_refs",
            )
            if not isinstance(systemRequiredEvidenceRefs, list):
                systemRequiredEvidenceRefs = []
                candidateReview["system_required_evidence_refs"] = (
                    systemRequiredEvidenceRefs
                )
            if requiredEvidenceId in systemRequiredEvidenceRefs:
                continue
            systemRequiredEvidenceRefs.append(requiredEvidenceId)

    def _ParseResponseText(
        self,
        responseText: str,
        issues: List[Stage1ResponseValidationIssue],
    ) -> Optional[Dict[str, Any]]:
        strippedText = responseText.strip()
        if strippedText == "":
            self._AddIssue(
                issues,
                "error",
                "empty_response",
                "$",
                "LLM response text is empty.",
            )
            return None

        jsonText = self._ExtractJsonObjectText(strippedText)
        if jsonText is None:
            self._AddIssue(
                issues,
                "error",
                "json_object_not_found",
                "$",
                "LLM response does not contain a JSON object.",
            )
            return None

        try:
            parsedResponse = json.loads(jsonText)
        except json.JSONDecodeError as error:
            self._AddIssue(
                issues,
                "error",
                "invalid_json",
                "$",
                "LLM response is not valid JSON: {0}".format(error),
            )
            return None

        if not isinstance(parsedResponse, dict):
            self._AddIssue(
                issues,
                "error",
                "json_root_not_object",
                "$",
                "LLM response root must be a JSON object.",
            )
            return None

        return parsedResponse

    def _ExtractJsonObjectText(self, responseText: str) -> Optional[str]:
        directText = responseText.strip()
        if directText.startswith("{"):
            return directText

        fencedText = self._ExtractFencedJsonText(directText)
        if fencedText is not None:
            return fencedText

        return self._ExtractBalancedJsonObjectText(directText)

    def _ExtractFencedJsonText(self, responseText: str) -> Optional[str]:
        fencePattern = re.compile(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            re.IGNORECASE | re.DOTALL,
        )
        match = fencePattern.search(responseText)
        if match is None:
            return None
        return match.group(1).strip()

    def _ExtractBalancedJsonObjectText(self, responseText: str) -> Optional[str]:
        decoder = json.JSONDecoder()
        searchIndex = 0
        while searchIndex < len(responseText):
            objectStartIndex = responseText.find("{", searchIndex)
            if objectStartIndex < 0:
                return None

            try:
                parsedValue, objectEndIndex = decoder.raw_decode(
                    responseText[objectStartIndex:],
                )
            except json.JSONDecodeError:
                searchIndex = objectStartIndex + 1
                continue

            if isinstance(parsedValue, dict):
                return responseText[
                    objectStartIndex : objectStartIndex + objectEndIndex
                ].strip()

            searchIndex = objectStartIndex + 1

        return None

    def _ValidateClassificationResult(
        self,
        parsedResponse: Mapping[str, Any],
        productInput: ProductClassificationInput,
        candidates: Sequence[CnCandidate],
        evidencePackage: Optional[Stage1EvidencePackage],
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        classificationResult = parsedResponse.get("classification_result")
        if not isinstance(classificationResult, Mapping):
            self._AddIssue(
                issues,
                "error",
                "missing_classification_result",
                "$.classification_result",
                "Response must contain classification_result object.",
            )
            return

        self._ValidateProductIdentity(classificationResult, productInput, issues)
        self._ValidateCandidateReviews(
            classificationResult,
            candidates,
            evidencePackage,
            issues,
        )
        self._ValidateHumanReviewWarning(classificationResult, issues)

    def _ValidateProductIdentity(
        self,
        classificationResult: Mapping[str, Any],
        productInput: ProductClassificationInput,
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        productName = classificationResult.get("product_name")
        if not isinstance(productName, str) or productName.strip() == "":
            self._AddIssue(
                issues,
                "warning",
                "missing_product_name",
                "$.classification_result.product_name",
                "classification_result.product_name is missing or empty.",
            )

        productDomain = classificationResult.get("product_domain")
        expectedDomain = productInput.productDomain
        if productDomain != expectedDomain:
            self._AddIssue(
                issues,
                "warning",
                "product_domain_mismatch",
                "$.classification_result.product_domain",
                "Expected product_domain '{0}', got '{1}'.".format(
                    expectedDomain,
                    productDomain,
                ),
            )

    def _ValidateCandidateReviews(
        self,
        classificationResult: Mapping[str, Any],
        candidates: Sequence[CnCandidate],
        evidencePackage: Optional[Stage1EvidencePackage],
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        candidateReviews = classificationResult.get("candidate_reviews")
        if not isinstance(candidateReviews, list):
            self._AddIssue(
                issues,
                "error",
                "missing_candidate_reviews",
                "$.classification_result.candidate_reviews",
                "candidate_reviews must be a list.",
            )
            return

        candidateByHs8 = {candidate.hs8: candidate for candidate in candidates}
        expectedHs8Set = set(candidateByHs8.keys())
        reviewedHs8List: List[str] = []

        for index, candidateReview in enumerate(candidateReviews):
            fieldPath = "$.classification_result.candidate_reviews[{0}]".format(
                index,
            )
            if not isinstance(candidateReview, Mapping):
                self._AddIssue(
                    issues,
                    "error",
                    "candidate_review_not_object",
                    fieldPath,
                    "Each candidate review must be an object.",
                )
                continue

            hs8 = candidateReview.get("hs8")
            if not isinstance(hs8, str) or hs8.strip() == "":
                self._AddIssue(
                    issues,
                    "error",
                    "missing_candidate_hs8",
                    fieldPath + ".hs8",
                    "Candidate review must include hs8.",
                )
            elif hs8 not in expectedHs8Set:
                self._AddIssue(
                    issues,
                    "error",
                    "unknown_candidate_hs8",
                    fieldPath + ".hs8",
                    "Candidate review contains unknown hs8: {0}.".format(hs8),
                )
            else:
                reviewedHs8List.append(hs8)

            status = candidateReview.get("status")
            if status not in STAGE1_CLASSIFICATION_ALLOWED_STATUSES:
                self._AddIssue(
                    issues,
                    "error",
                    "invalid_candidate_status",
                    fieldPath + ".status",
                    "Candidate status is not one of the allowed values.",
                )

            humanReviewRequired = candidateReview.get("human_review_required")
            if humanReviewRequired is not True:
                self._AddIssue(
                    issues,
                    "error",
                    "human_review_required_not_true",
                    fieldPath + ".human_review_required",
                    "human_review_required must be true for every candidate.",
                )

            reason = candidateReview.get("reason")
            if not isinstance(reason, str) or reason.strip() == "":
                self._AddIssue(
                    issues,
                    "warning",
                    "missing_candidate_reason",
                    fieldPath + ".reason",
                    "Candidate review should include a reason.",
                )

            if isinstance(hs8, str) and hs8 in expectedHs8Set:
                self._ValidateEvidenceRefs(
                    candidateReview,
                    hs8,
                    evidencePackage,
                    fieldPath,
                    issues,
                )
                self._ValidateClassificationPathReview(
                    candidateReview,
                    candidateByHs8[hs8],
                    fieldPath,
                    issues,
                )
                self._ValidateClassificationRuleReview(
                    candidateReview,
                    fieldPath,
                    issues,
                )
                self._ValidateSimilarEbtiCases(
                    candidateReview,
                    hs8,
                    evidencePackage,
                    fieldPath,
                    issues,
                )

        self._ValidateCandidateCoverage(
            reviewedHs8List,
            expectedHs8Set,
            issues,
        )

    def _ValidateEvidenceRefs(
        self,
        candidateReview: Mapping[str, Any],
        hs8: str,
        evidencePackage: Optional[Stage1EvidencePackage],
        fieldPath: str,
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        if evidencePackage is None:
            return

        evidenceRefs = candidateReview.get("evidence_refs")
        if not isinstance(evidenceRefs, list):
            self._AddIssue(
                issues,
                "error",
                "missing_evidence_refs",
                fieldPath + ".evidence_refs",
                "Candidate review must include evidence_refs when evidence package is provided.",
            )
            return

        if not evidenceRefs:
            self._AddIssue(
                issues,
                "error",
                "empty_evidence_refs",
                fieldPath + ".evidence_refs",
                "Candidate review must cite at least one evidence_ref when evidence package is provided.",
            )
            return

        validEvidenceIds = evidencePackage.validEvidenceIds
        candidateEvidenceIds = set(evidencePackage.candidateEvidenceIds.get(hs8, []))
        candidateSpecificEvidenceIds = {
            evidenceRecord.evidenceId
            for evidenceRecord in evidencePackage.evidenceRecords
            if evidenceRecord.candidateHs8 == hs8
        }
        citedValidEvidenceIds: Set[str] = set()
        for evidenceIndex, evidenceRef in enumerate(evidenceRefs):
            evidencePath = "{0}.evidence_refs[{1}]".format(fieldPath, evidenceIndex)
            if not isinstance(evidenceRef, str) or evidenceRef.strip() == "":
                self._AddIssue(
                    issues,
                    "error",
                    "invalid_evidence_ref",
                    evidencePath,
                    "evidence_refs entries must be non-empty strings.",
                )
                continue
            if evidenceRef not in validEvidenceIds:
                self._AddIssue(
                    issues,
                    "error",
                    "unknown_evidence_ref",
                    evidencePath,
                    "Evidence ref is not in the provided evidence package: {0}.".format(
                        evidenceRef,
                    ),
                )
                continue
            citedValidEvidenceIds.add(evidenceRef)
            if evidenceRef not in candidateEvidenceIds:
                self._AddIssue(
                    issues,
                    "warning",
                    "candidate_unrelated_evidence_ref",
                    evidencePath,
                    "Evidence ref is valid but not mapped to candidate hs8 {0}: {1}.".format(
                        hs8,
                        evidenceRef,
                    ),
                )

        candidateSpecificCitations = citedValidEvidenceIds.intersection(
            candidateSpecificEvidenceIds,
        )
        status = candidateReview.get("status")
        if (
            status in {"strong_candidate", "possible_candidate"}
            and not candidateSpecificCitations
        ):
            self._AddIssue(
                issues,
                "error",
                "missing_candidate_specific_evidence_ref",
                fieldPath + ".evidence_refs",
                (
                    "strong_candidate or possible_candidate must cite at least "
                    "one candidate-specific evidence ref for hs8 {0}."
                ).format(hs8),
            )
        elif (
            status == "unlikely_candidate"
            and not candidateSpecificCitations
        ):
            self._AddIssue(
                issues,
                "warning",
                "missing_candidate_specific_evidence_ref",
                fieldPath + ".evidence_refs",
                (
                    "unlikely_candidate should cite candidate-specific evidence "
                    "when rejecting hs8 {0}."
                ).format(hs8),
            )

    def _ValidateCandidateCoverage(
        self,
        reviewedHs8List: Sequence[str],
        expectedHs8Set: Set[str],
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        reviewedHs8Set = set(reviewedHs8List)
        missingHs8Codes = sorted(expectedHs8Set.difference(reviewedHs8Set))
        duplicateHs8Codes = sorted(
            hs8
            for hs8 in reviewedHs8Set
            if reviewedHs8List.count(hs8) > 1
        )

        if missingHs8Codes:
            self._AddIssue(
                issues,
                "warning",
                "missing_candidate_reviews_for_input_codes",
                "$.classification_result.candidate_reviews",
                "Missing reviews for input hs8 codes: {0}.".format(
                    ", ".join(missingHs8Codes),
                ),
            )

        if duplicateHs8Codes:
            self._AddIssue(
                issues,
                "warning",
                "duplicate_candidate_reviews",
                "$.classification_result.candidate_reviews",
                "Duplicate candidate reviews for hs8 codes: {0}.".format(
                    ", ".join(duplicateHs8Codes),
                ),
            )

    def _ValidateClassificationPathReview(
        self,
        candidateReview: Mapping[str, Any],
        candidate: CnCandidate,
        fieldPath: str,
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        pathReview = candidateReview.get("classification_path_review")
        pathFieldPath = fieldPath + ".classification_path_review"
        if not isinstance(pathReview, Mapping):
            self._AddIssue(
                issues,
                "error",
                "missing_classification_path_review",
                pathFieldPath,
                "Candidate review must include classification_path_review object.",
            )
            return

        expectedCodes = {
            "hs2": candidate.hs2Code,
            "hs4": candidate.hs4Code,
            "hs6": candidate.hs6Code,
            "cn8": candidate.hs8Code or candidate.hs8,
        }
        reviewedCodes: Dict[str, str] = {}

        for level in STAGE1_CLASSIFICATION_PATH_LEVELS:
            levelReview = pathReview.get(level)
            levelFieldPath = "{0}.{1}".format(pathFieldPath, level)
            if not isinstance(levelReview, Mapping):
                self._AddIssue(
                    issues,
                    "error",
                    "missing_classification_path_level_review",
                    levelFieldPath,
                    "classification_path_review must include {0} object.".format(
                        level,
                    ),
                )
                continue

            code = levelReview.get("code")
            if code is not None and not isinstance(code, str):
                self._AddIssue(
                    issues,
                    "error",
                    "invalid_classification_path_code",
                    levelFieldPath + ".code",
                    "Path review code must be string or null.",
                )
            elif isinstance(code, str) and code.strip() != "":
                normalizedCode = NormalizeWhitespace(code)
                reviewedCodes[level] = normalizedCode
                expectedCode = expectedCodes.get(level)
                if expectedCode is not None and normalizedCode != expectedCode:
                    self._AddIssue(
                        issues,
                        "warning",
                        "classification_path_candidate_code_mismatch",
                        levelFieldPath + ".code",
                        (
                            "Path review {0} code should match candidate code "
                            "{1}, got {2}."
                        ).format(level, expectedCode, normalizedCode),
                    )

            consistency = levelReview.get("consistency")
            if consistency not in STAGE1_CLASSIFICATION_PATH_ALLOWED_CONSISTENCIES:
                self._AddIssue(
                    issues,
                    "error",
                    "invalid_classification_path_consistency",
                    levelFieldPath + ".consistency",
                    (
                        "Path review consistency must be one of: {0}."
                    ).format(
                        ", ".join(
                            sorted(
                                STAGE1_CLASSIFICATION_PATH_ALLOWED_CONSISTENCIES,
                            )
                        ),
                    ),
                )

            comment = levelReview.get("comment")
            if not isinstance(comment, str) or comment.strip() == "":
                self._AddIssue(
                    issues,
                    "warning",
                    "missing_classification_path_comment",
                    levelFieldPath + ".comment",
                    "Path review should include a non-empty comment.",
                )

        for childLevel, parentLevel in [
            ("hs4", "hs2"),
            ("hs6", "hs4"),
            ("cn8", "hs6"),
        ]:
            childCode = reviewedCodes.get(childLevel)
            parentCode = reviewedCodes.get(parentLevel)
            if childCode is None or parentCode is None:
                continue
            if not childCode.startswith(parentCode):
                self._AddIssue(
                    issues,
                    "error",
                    "classification_path_prefix_mismatch",
                    "{0}.{1}.code".format(pathFieldPath, childLevel),
                    "{0} code {1} must start with {2} code {3}.".format(
                        childLevel,
                        childCode,
                        parentLevel,
                        parentCode,
                    ),
                )

    def _ValidateClassificationRuleReview(
        self,
        candidateReview: Mapping[str, Any],
        fieldPath: str,
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        ruleReview = candidateReview.get("classification_rule_review")
        ruleFieldPath = fieldPath + ".classification_rule_review"
        if not isinstance(ruleReview, Mapping):
            self._AddIssue(
                issues,
                "error",
                "missing_classification_rule_review",
                ruleFieldPath,
                "Candidate review must include classification_rule_review object.",
            )
            return

        for fieldName in [
            "include_rule_comment",
            "exclude_rule_comment",
            "hard_condition_comment",
        ]:
            value = ruleReview.get(fieldName)
            if not isinstance(value, str) or value.strip() == "":
                self._AddIssue(
                    issues,
                    "warning",
                    "missing_classification_rule_comment",
                    "{0}.{1}".format(ruleFieldPath, fieldName),
                    "{0} should be a non-empty string.".format(fieldName),
                )

    def _ValidateSimilarEbtiCases(
        self,
        candidateReview: Mapping[str, Any],
        hs8: str,
        evidencePackage: Optional[Stage1EvidencePackage],
        fieldPath: str,
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        similarCases = candidateReview.get("similar_ebti_cases")
        similarCasesFieldPath = fieldPath + ".similar_ebti_cases"
        if not isinstance(similarCases, list):
            self._AddIssue(
                issues,
                "warning",
                "missing_similar_ebti_cases",
                similarCasesFieldPath,
                "Candidate review should include similar_ebti_cases list.",
            )
            return

        if evidencePackage is None:
            return

        evidenceRecordsById: Dict[str, List[Stage1EvidenceRecord]] = {}
        for evidenceRecord in evidencePackage.evidenceRecords:
            evidenceRecordsById.setdefault(evidenceRecord.evidenceId, []).append(
                evidenceRecord,
            )
        for caseIndex, similarCase in enumerate(similarCases):
            caseFieldPath = "{0}[{1}]".format(similarCasesFieldPath, caseIndex)
            if not isinstance(similarCase, Mapping):
                self._AddIssue(
                    issues,
                    "error",
                    "similar_ebti_case_not_object",
                    caseFieldPath,
                    "similar_ebti_cases entries must be objects.",
                )
                continue

            evidenceRef = similarCase.get("evidence_ref")
            if not isinstance(evidenceRef, str) or evidenceRef.strip() == "":
                self._AddIssue(
                    issues,
                    "error",
                    "invalid_similar_ebti_evidence_ref",
                    caseFieldPath + ".evidence_ref",
                    "similar_ebti_cases evidence_ref must be a non-empty string.",
                )
                continue

            evidenceRecords = evidenceRecordsById.get(evidenceRef, [])
            if not evidenceRecords:
                self._AddIssue(
                    issues,
                    "error",
                    "unknown_similar_ebti_evidence_ref",
                    caseFieldPath + ".evidence_ref",
                    "similar EBTI evidence_ref is not in evidence package: {0}.".format(
                        evidenceRef,
                    ),
                )
                continue

            if not any(
                evidenceRecord.evidenceType == "bti_case_chunk"
                for evidenceRecord in evidenceRecords
            ):
                self._AddIssue(
                    issues,
                    "warning",
                    "similar_ebti_ref_not_bti_case",
                    caseFieldPath + ".evidence_ref",
                    "similar EBTI evidence_ref should point to bti_case_chunk.",
                )
            if not any(
                evidenceRecord.candidateHs8 == hs8
                for evidenceRecord in evidenceRecords
            ):
                self._AddIssue(
                    issues,
                    "warning",
                    "similar_ebti_ref_candidate_mismatch",
                    caseFieldPath + ".evidence_ref",
                    "similar EBTI evidence_ref is not mapped to candidate hs8 {0}.".format(
                        hs8,
                    ),
                )

            for fieldName in ["similarity_comment", "difference_comment"]:
                value = similarCase.get(fieldName)
                if not isinstance(value, str) or value.strip() == "":
                    self._AddIssue(
                        issues,
                        "warning",
                        "missing_similar_ebti_comment",
                        "{0}.{1}".format(caseFieldPath, fieldName),
                        "{0} should be a non-empty string.".format(fieldName),
                    )

    def _ValidateHumanReviewWarning(
        self,
        classificationResult: Mapping[str, Any],
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        humanReviewWarning = classificationResult.get("human_review_warning")
        if (
            not isinstance(humanReviewWarning, str)
            or humanReviewWarning.strip() == ""
        ):
            self._AddIssue(
                issues,
                "warning",
                "missing_human_review_warning",
                "$.classification_result.human_review_warning",
                "Response should include a human review warning.",
            )

    def _DetectFinalDeterminationLanguage(
        self,
        responseText: str,
        issues: List[Stage1ResponseValidationIssue],
    ) -> None:
        normalizedResponseText = responseText.lower()
        for warningTerm in FINAL_DETERMINATION_WARNING_TERMS:
            if warningTerm.lower() not in normalizedResponseText:
                continue
            self._AddIssue(
                issues,
                "warning",
                "final_determination_language_detected",
                "$",
                "Response contains final-determination language: {0}.".format(
                    warningTerm,
                ),
            )
            return

    def _AddIssue(
        self,
        issues: List[Stage1ResponseValidationIssue],
        severity: str,
        issueCode: str,
        fieldPath: str,
        message: str,
    ) -> None:
        issues.append(
            Stage1ResponseValidationIssue(
                severity=severity,
                issueCode=issueCode,
                fieldPath=fieldPath,
                message=message,
            )
        )
