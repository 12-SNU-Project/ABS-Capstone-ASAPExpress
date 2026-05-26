"""Ontology 기반 Stage 1 CN 후보 조회 helper."""

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from eu_export.bridge import LlmGenerationOptions, LlmRequest, LlmResponseFormat
from eu_export.ontology.loader import OntologyDocumentLoader
from eu_export.ontology.schema import PackagedOntologyContext
from eu_export.utils import NormalizeWhitespace, NormalizeWhitespacePreservingLines


CN_LEAF_CODE_CARDS_DOCUMENT_ID = "table.cn_leaf_code_cards"
FOOD_DOMAIN_SCOPE = "food_16_21"
COSMETICS_DOMAIN_SCOPE = "cosmetics_33"
DEFAULT_CN_CANDIDATE_TOP_K = 8
DEFAULT_STAGE1_CLASSIFICATION_MAX_TOKENS = 1800
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
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
        parts = [
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
    hs6Code: Optional[str] = None
    hs6Description: Optional[str] = None
    hs8Description: Optional[str] = None
    combinedDescription: str = ""
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
            "hs6_code": self.hs6Code,
            "hs6_description": self.hs6Description,
            "hs8_description": self.hs8Description,
            "combined_description": self.combinedDescription,
            "hard_conditions": self.hardConditions,
            "cn_explanatory_note": self.cnExplanatoryNote,
            "needs_human_review": self.needsHumanReview,
        }


class ProductClassificationInputNormalizer:
    """product pipeline 결과를 Stage 1 후보 조회 입력으로 변환한다."""

    def BuildFromKurlyPipelineResultData(
        self,
        pipelineResultData: Mapping[str, Any],
    ) -> ProductClassificationInput:
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
            ),
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
        if not rawTexts:
            rawTexts = [
                rawText
                for rawText in (
                    self._ReadString(noticeField.get("raw_text"))
                    for noticeField in noticeFields
                )
                if rawText is not None
            ]
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

        if not candidates:
            return self._BuildFallbackCandidates(
                rowsByDomainScope=rowsByDomainScope,
                domainScopes=productInput.domainScopes,
                topK=topK,
            )

        return sorted(
            candidates,
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
        score += 4.0 * len(includeMatches)
        score += 2.0 * len(searchKeywordMatches)
        score += 1.0 * len(descriptionMatches)
        score -= 5.0 * len(excludeMatches)

        if score < 0:
            score = 0.0

        return self._BuildCandidate(
            row=row,
            domainScope=domainScope,
            score=score,
            matchedTerms=sorted(matchedTerms),
            excludedTerms=sorted(excludedTerms),
        )

    def _BuildFallbackCandidates(
        self,
        rowsByDomainScope: Mapping[str, List[Dict[str, str]]],
        domainScopes: Sequence[str],
        topK: int,
    ) -> List[CnCandidate]:
        fallbackCandidates: List[CnCandidate] = []
        for domainScope in domainScopes:
            for row in rowsByDomainScope.get(domainScope, []):
                fallbackCandidates.append(
                    self._BuildCandidate(
                        row=row,
                        domainScope=domainScope,
                        score=0.0,
                        matchedTerms=[],
                        excludedTerms=[],
                    )
                )
                if len(fallbackCandidates) >= topK:
                    return fallbackCandidates
        return fallbackCandidates

    def _BuildCandidate(
        self,
        row: Mapping[str, str],
        domainScope: str,
        score: float,
        matchedTerms: Sequence[str],
        excludedTerms: Sequence[str],
    ) -> CnCandidate:
        return CnCandidate(
            hs8=row.get("hs8", ""),
            domainScope=domainScope,
            score=round(score, 3),
            matchedTerms=list(matchedTerms),
            excludedTerms=list(excludedTerms),
            hs6Code=row.get("hs6_code") or None,
            hs6Description=row.get("hs6_description") or None,
            hs8Description=row.get("hs8_description") or None,
            combinedDescription=row.get("combined_description", ""),
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


class Stage1ClassificationRequestBuilder:
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
        userPrompt: Optional[str] = None,
        maxCandidateCount: int = DEFAULT_CN_CANDIDATE_TOP_K,
    ) -> LlmRequest:
        contextChunks = [
            self._BuildProductContextChunk(productInput),
            self._BuildCandidateContextChunk(candidates[:maxCandidateCount]),
            *packagedContext.contextChunks,
        ]
        return LlmRequest(
            userPrompt=userPrompt or self._BuildDefaultUserPrompt(productInput),
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
                json.dumps(productData, ensure_ascii=False, indent=2),
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
                    [candidate.ToDict() for candidate in candidates],
                    ensure_ascii=False,
                    indent=2,
                ),
            ]
        )

    def _BuildDefaultUserPrompt(
        self,
        productInput: ProductClassificationInput,
    ) -> str:
        instructions = json.dumps(
            STAGE1_CLASSIFICATION_JSON_INSTRUCTIONS,
            ensure_ascii=False,
            indent=2,
        )
        return "\n".join(
            [
                "아래 product facts와 CN candidate cards를 검토해 Stage 1 HS6/CN8 후보 검토 JSON을 작성하라.",
                "최종 법적/통관 판단으로 표현하지 말고, 후보별 가능성·배제 근거·부족 정보를 구분하라.",
                "상품명: {0}".format(productInput.productName or "unknown"),
                "응답 JSON 구조:",
                instructions,
            ]
        )
