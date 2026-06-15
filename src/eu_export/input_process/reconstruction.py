"""Product input reconstruction from notice, table OCR, and raw OCR evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from eu_export.bridge import (
    LlmGenerationOptions,
    LlmRequest,
    LlmResponseFormat,
    RuntimeAdapter,
)
from eu_export.input_process.dictionary import (
    DEFAULT_PRODUCT_INPUT_DICTIONARY_PATH,
    ProductDictionaryMatch,
    ProductDictionaryRepository,
    ProductDictionaryRetriever,
)
from eu_export.product.ocr.ocr_normalization import ProductOcrFactNormalizer
from eu_export.utils import NormalizeWhitespace, NormalizeWhitespacePreservingLines


PRODUCT_FACT_RECONSTRUCTION_SYSTEM_PROMPT = """
You reconstruct structured product input facts from Korean product notice, PP-Structure table OCR, raw OCR text, and deterministic dictionary matches.
Return strict JSON only.
Do not infer HS, CN, TARIC, customs, legal, or regulatory conclusions.
Do not create product facts that are absent from the provided evidence.
Do not invent ingredient names outside dictionary matches when correcting OCR text.
If evidence is insufficient or conflicting, use unresolved_facts or conflicts.
""".strip()

PRODUCT_FACT_RECONSTRUCTION_FEW_SHOT_EXAMPLES = [
    {
        "input": {
            "evidence": [
                {
                    "evidence_id": "table-1",
                    "source_type": "pp_table",
                    "text": "영양성분 나트류 320mg 탄수하물 40g 단백질 8g",
                }
            ],
            "dictionary_matches": [
                {
                    "raw_text": "나트류",
                    "matched_text": "나트류",
                    "canonical_name": "나트륨",
                    "term_type": "nutrition_label",
                    "match_type": "alias",
                    "source_ref": "dictionary:nutrition_label_sodium:nutrition_001",
                    "correction_action": "auto_corrected",
                },
                {
                    "raw_text": "탄수하물",
                    "matched_text": "탄수하물",
                    "canonical_name": "탄수화물",
                    "term_type": "nutrition_label",
                    "match_type": "alias",
                    "source_ref": "dictionary:nutrition_label_carbohydrate:nutrition_002",
                    "correction_action": "auto_corrected",
                },
            ],
        },
        "output": {
            "product_facts": [
                {
                    "field_name": "영양성분",
                    "raw_value": "나트류 320mg 탄수하물 40g 단백질 8g",
                    "normalized_value": "나트륨 320mg 탄수화물 40g 단백질 8g",
                    "source_refs": ["table-1"],
                    "correction_type": "llm_reconstructed",
                    "validation_status": "accepted",
                }
            ],
            "unresolved_facts": [],
            "conflicts": [],
            "normalized_fact_texts": [
                "영양성분: 나트륨 320mg 탄수화물 40g 단백질 8g"
            ],
            "warnings": [],
            "used_llm_reconstruction": True,
            "fallback_reason": None,
            "dictionary_matches": [],
        },
    }
]


class ProductInputEvidenceRecord(BaseModel):
    """상품 input 복원을 위한 원천 evidence record."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    evidenceId: str = Field(alias="evidence_id")
    sourceType: str = Field(alias="source_type")
    text: str
    sourceRef: Optional[str] = Field(default=None, alias="source_ref")


class ProductInputEvidencePackage(BaseModel):
    """상품 input 복원 단계에 전달되는 evidence 묶음."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    productPageUrl: Optional[str] = Field(default=None, alias="product_page_url")
    records: List[ProductInputEvidenceRecord] = Field(default_factory=list)


class ProductFactRecord(BaseModel):
    """복원된 상품 input fact."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    fieldName: str = Field(alias="field_name")
    rawValue: str = Field(default="", alias="raw_value")
    normalizedValue: str = Field(default="", alias="normalized_value")
    sourceRefs: List[str] = Field(default_factory=list, alias="source_refs")
    correctionType: str = Field(default="none", alias="correction_type")
    validationStatus: str = Field(default="accepted", alias="validation_status")

    def ToFactText(self) -> str:
        normalizedFieldName = NormalizeWhitespace(self.fieldName)
        normalizedValue = NormalizeWhitespacePreservingLines(self.normalizedValue)
        if normalizedFieldName == "":
            return normalizedValue
        if normalizedValue == "":
            return normalizedFieldName
        if normalizedValue.startswith("{0}:".format(normalizedFieldName)):
            return normalizedValue
        return "{0}: {1}".format(normalizedFieldName, normalizedValue)


class ProductFactReconstructionResult(BaseModel):
    """상품 input 복원 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    productFacts: List[ProductFactRecord] = Field(
        default_factory=list,
        alias="product_facts",
    )
    unresolvedFacts: List[ProductFactRecord] = Field(
        default_factory=list,
        alias="unresolved_facts",
    )
    conflicts: List[str] = Field(default_factory=list)
    normalizedFactTexts: List[str] = Field(
        default_factory=list,
        alias="normalized_fact_texts",
    )
    warnings: List[str] = Field(default_factory=list)
    usedLlmReconstruction: bool = Field(
        default=False,
        alias="used_llm_reconstruction",
    )
    fallbackReason: Optional[str] = Field(default=None, alias="fallback_reason")
    dictionaryMatches: List[ProductDictionaryMatch] = Field(
        default_factory=list,
        alias="dictionary_matches",
    )


class _BoundModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        extra="ignore",
    )


class _BoundNoticeField(_BoundModel):
    fieldName: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("fieldName", "field_name"),
    )
    fieldValue: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("fieldValue", "field_value"),
    )


class _BoundNoticeOption(_BoundModel):
    optionName: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("optionName", "option_name"),
    )
    fields: List[_BoundNoticeField] = Field(default_factory=list)


class _BoundParsedProductPage(_BoundModel):
    productNoticeFields: List[_BoundNoticeField] = Field(
        default_factory=list,
        validation_alias=AliasChoices("productNoticeFields", "product_notice_fields"),
    )
    productNoticeOptions: List[_BoundNoticeOption] = Field(
        default_factory=list,
        validation_alias=AliasChoices("productNoticeOptions", "product_notice_options"),
    )


class _BoundCollectionResult(_BoundModel):
    productPageUrl: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("productPageUrl", "product_page_url"),
    )
    parsedProductPage: _BoundParsedProductPage = Field(
        default_factory=_BoundParsedProductPage,
        validation_alias=AliasChoices("parsedProductPage", "parsed_product_page"),
    )


class _BoundOcrTable(_BoundModel):
    plainText: str = Field(
        default="",
        validation_alias=AliasChoices("plainText", "plain_text"),
    )


class _BoundRawTileText(_BoundModel):
    tileIndex: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("tileIndex", "tile_index"),
    )
    text: str = ""


class _BoundStructuredOcr(_BoundModel):
    tables: List[_BoundOcrTable] = Field(default_factory=list)
    rawTileTexts: List[_BoundRawTileText] = Field(
        default_factory=list,
        validation_alias=AliasChoices("rawTileTexts", "raw_tile_texts"),
    )


class _BoundOcrImageResult(_BoundModel):
    structuredOcr: _BoundStructuredOcr = Field(
        default_factory=_BoundStructuredOcr,
        validation_alias=AliasChoices("structuredOcr", "structured_ocr"),
    )


class ProductInputEvidenceBuilder:
    """Kurly 수집/OCR 산출물을 input reconstruction evidence로 변환한다."""

    def BuildFromPipelineParts(
        self,
        collectionResult: Any,
        ocrImageResults: Sequence[Any],
        combinedOcrText: str,
    ) -> ProductInputEvidencePackage:
        records: List[ProductInputEvidenceRecord] = []
        boundCollectionResult = _BoundCollectionResult.model_validate(collectionResult)
        boundOcrImageResults = [
            _BoundOcrImageResult.model_validate(ocrImageResult)
            for ocrImageResult in ocrImageResults
        ]
        self._AppendNoticeEvidence(records, boundCollectionResult.parsedProductPage)
        self._AppendOcrEvidence(records, boundOcrImageResults)
        if not any(record.sourceType.startswith("raw_ocr") for record in records):
            self._AppendRecord(
                records,
                sourceType="raw_ocr",
                text=combinedOcrText,
                sourceRef="combined_ocr_text",
            )
        return ProductInputEvidencePackage(
            productPageUrl=boundCollectionResult.productPageUrl,
            records=records,
        )

    def _AppendNoticeEvidence(
        self,
        records: List[ProductInputEvidenceRecord],
        parsedProductPage: _BoundParsedProductPage,
    ) -> None:
        for optionIndex, noticeOption in enumerate(
            parsedProductPage.productNoticeOptions,
            start=1,
        ):
            if noticeOption.optionName is not None:
                self._AppendRecord(
                    records,
                    sourceType="notice_option",
                    text=noticeOption.optionName,
                    sourceRef="notice-option-{0}".format(optionIndex),
                )
            for fieldIndex, field in enumerate(noticeOption.fields, start=1):
                self._AppendNoticeFieldRecord(
                    records,
                    field,
                    "notice-option-{0}-field-{1}".format(optionIndex, fieldIndex),
                )
        if parsedProductPage.productNoticeOptions:
            return
        for fieldIndex, field in enumerate(
            parsedProductPage.productNoticeFields,
            start=1,
        ):
            self._AppendNoticeFieldRecord(
                records,
                field,
                "notice-field-{0}".format(fieldIndex),
            )

    def _AppendNoticeFieldRecord(
        self,
        records: List[ProductInputEvidenceRecord],
        field: _BoundNoticeField,
        sourceRef: str,
    ) -> None:
        if field.fieldName is None and field.fieldValue is None:
            return
        if field.fieldName is not None and field.fieldValue is not None:
            text = "{0}: {1}".format(field.fieldName, field.fieldValue)
        else:
            text = field.fieldName if field.fieldName is not None else field.fieldValue
        self._AppendRecord(
            records,
            sourceType="notice_field",
            text=text or "",
            sourceRef=sourceRef,
        )

    def _AppendOcrEvidence(
        self,
        records: List[ProductInputEvidenceRecord],
        ocrImageResults: Sequence[_BoundOcrImageResult],
    ) -> None:
        for imageIndex, imageResult in enumerate(ocrImageResults, start=1):
            for tableIndex, table in enumerate(imageResult.structuredOcr.tables, start=1):
                self._AppendRecord(
                    records,
                    sourceType="pp_table",
                    text=table.plainText,
                    sourceRef="image-{0}-table-{1}".format(imageIndex, tableIndex),
                )
            for rawTileText in imageResult.structuredOcr.rawTileTexts:
                self._AppendRecord(
                    records,
                    sourceType="raw_ocr_tile",
                    text=rawTileText.text,
                    sourceRef="image-{0}-tile-{1}".format(
                        imageIndex,
                        rawTileText.tileIndex if rawTileText.tileIndex is not None else 1,
                    ),
                )

    def _AppendRecord(
        self,
        records: List[ProductInputEvidenceRecord],
        sourceType: str,
        text: str,
        sourceRef: Optional[str],
    ) -> None:
        normalizedText = NormalizeWhitespacePreservingLines(text)
        if normalizedText == "":
            return
        records.append(
            ProductInputEvidenceRecord(
                evidenceId="evidence-{0}".format(len(records) + 1),
                sourceType=sourceType,
                text=normalizedText,
                sourceRef=sourceRef,
            )
        )


class ProductFactReconstructionValidator:
    """LLM 또는 deterministic 복원 결과의 source reference를 검증한다."""

    def Validate(
        self,
        result: ProductFactReconstructionResult,
        evidencePackage: ProductInputEvidencePackage,
    ) -> ProductFactReconstructionResult:
        validEvidenceIds = {record.evidenceId for record in evidencePackage.records}
        productFacts: List[ProductFactRecord] = []
        warnings = list(result.warnings)
        for factRecord in result.productFacts:
            invalidRefs = [
                sourceRef
                for sourceRef in factRecord.sourceRefs
                if sourceRef not in validEvidenceIds
            ]
            if invalidRefs:
                warnings.append(
                    "rejected_fact_invalid_source_refs field={0} refs={1}".format(
                        factRecord.fieldName,
                        ",".join(invalidRefs),
                    )
                )
                productFacts.append(
                    factRecord.model_copy(update={"validationStatus": "rejected"})
                )
                continue
            productFacts.append(factRecord)
        normalizedFactTexts = self._BuildNormalizedFactTexts(productFacts)
        if result.normalizedFactTexts:
            normalizedFactTexts = [
                factText
                for factText in result.normalizedFactTexts
                if NormalizeWhitespace(factText)
            ]
        return result.model_copy(
            update={
                "productFacts": productFacts,
                "normalizedFactTexts": normalizedFactTexts,
                "warnings": warnings,
            }
        )

    def _BuildNormalizedFactTexts(
        self,
        productFacts: Sequence[ProductFactRecord],
    ) -> List[str]:
        factTexts: List[str] = []
        seenFactTexts: set[str] = set()
        for factRecord in productFacts:
            if factRecord.validationStatus != "accepted":
                continue
            factText = factRecord.ToFactText()
            if factText and factText not in seenFactTexts:
                seenFactTexts.add(factText)
                factTexts.append(factText)
        return factTexts


class DeterministicProductFactReconstructor:
    """Dictionary correction과 기존 OCR normalizer로 기본 product facts를 만든다."""

    def __init__(
        self,
        dictionaryRetriever: ProductDictionaryRetriever,
        ocrFactNormalizer: Optional[ProductOcrFactNormalizer] = None,
        validator: Optional[ProductFactReconstructionValidator] = None,
    ) -> None:
        self._dictionaryRetriever = dictionaryRetriever
        self._ocrFactNormalizer = ocrFactNormalizer or ProductOcrFactNormalizer()
        self._validator = validator or ProductFactReconstructionValidator()

    def Reconstruct(
        self,
        evidencePackage: ProductInputEvidencePackage,
    ) -> ProductFactReconstructionResult:
        dictionaryMatches = self._dictionaryRetriever.FindMatches(
            [record.text for record in evidencePackage.records]
        )
        factRecords = self._BuildFactRecords(evidencePackage, dictionaryMatches)
        result = ProductFactReconstructionResult(
            productFacts=factRecords,
            normalizedFactTexts=[
                factRecord.ToFactText()
                for factRecord in factRecords
                if factRecord.validationStatus == "accepted"
            ],
            usedLlmReconstruction=False,
            fallbackReason="llm_reconstruction_not_used",
            dictionaryMatches=dictionaryMatches,
        )
        return self._validator.Validate(result, evidencePackage)

    def _BuildFactRecords(
        self,
        evidencePackage: ProductInputEvidencePackage,
        dictionaryMatches: Sequence[ProductDictionaryMatch],
    ) -> List[ProductFactRecord]:
        factRecords: List[ProductFactRecord] = []
        for record in evidencePackage.records:
            if record.sourceType == "notice_field":
                factRecord = self._BuildFactRecordFromText(record, dictionaryMatches)
                if factRecord is not None:
                    factRecords.append(factRecord)
        combinedText = "\n".join(record.text for record in evidencePackage.records)
        normalizedResult = self._ocrFactNormalizer.Normalize(combinedText)
        for factText in normalizedResult.factTexts:
            factRecord = self._BuildFactRecordFromNormalizedText(
                factText,
                evidencePackage,
                dictionaryMatches,
            )
            if factRecord is not None:
                factRecords.append(factRecord)
        return self._DeduplicateFactRecords(factRecords)

    def _BuildFactRecordFromText(
        self,
        record: ProductInputEvidenceRecord,
        dictionaryMatches: Sequence[ProductDictionaryMatch],
    ) -> Optional[ProductFactRecord]:
        splitText = self._SplitFieldText(record.text)
        if splitText is None:
            return None
        fieldName, fieldValue = splitText
        normalizedValue = self._ApplyAutoCorrections(fieldValue, dictionaryMatches)
        correctionType = (
            "dictionary_fuzzy"
            if normalizedValue != fieldValue
            and any(match.matchType == "fuzzy" for match in dictionaryMatches)
            else "dictionary_exact"
            if normalizedValue != fieldValue
            else "none"
        )
        return ProductFactRecord(
            fieldName=fieldName,
            rawValue=fieldValue,
            normalizedValue=normalizedValue,
            sourceRefs=[record.evidenceId],
            correctionType=correctionType,
            validationStatus="accepted",
        )

    def _BuildFactRecordFromNormalizedText(
        self,
        factText: str,
        evidencePackage: ProductInputEvidencePackage,
        dictionaryMatches: Sequence[ProductDictionaryMatch],
    ) -> Optional[ProductFactRecord]:
        sourceRefs = self._FindSourceRefs(factText, evidencePackage)
        if not sourceRefs:
            sourceRefs = [evidencePackage.records[0].evidenceId] if evidencePackage.records else []
        splitText = self._SplitFieldText(factText)
        if splitText is None:
            fieldName = "OCR 관찰 정보"
            fieldValue = factText
        else:
            fieldName, fieldValue = splitText
        normalizedValue = self._ApplyAutoCorrections(fieldValue, dictionaryMatches)
        return ProductFactRecord(
            fieldName=fieldName,
            rawValue=fieldValue,
            normalizedValue=normalizedValue,
            sourceRefs=sourceRefs,
            correctionType="dictionary_exact" if normalizedValue != fieldValue else "none",
            validationStatus="accepted",
        )

    def _ApplyAutoCorrections(
        self,
        text: str,
        dictionaryMatches: Sequence[ProductDictionaryMatch],
    ) -> str:
        normalizedText = text
        for dictionaryMatch in dictionaryMatches:
            if dictionaryMatch.correctionAction != "auto_corrected":
                continue
            if dictionaryMatch.matchedText == dictionaryMatch.canonicalName:
                continue
            normalizedText = normalizedText.replace(
                dictionaryMatch.matchedText,
                dictionaryMatch.canonicalName,
            )
        return normalizedText

    def _FindSourceRefs(
        self,
        factText: str,
        evidencePackage: ProductInputEvidencePackage,
    ) -> List[str]:
        normalizedFactText = NormalizeWhitespace(factText)
        sourceRefs: List[str] = []
        for record in evidencePackage.records:
            if normalizedFactText in NormalizeWhitespace(record.text):
                sourceRefs.append(record.evidenceId)
        return sourceRefs

    def _SplitFieldText(self, text: str) -> Optional[tuple[str, str]]:
        normalizedText = NormalizeWhitespacePreservingLines(text)
        for separator in [":", "："]:
            if separator in normalizedText:
                fieldName, fieldValue = normalizedText.split(separator, 1)
                fieldName = NormalizeWhitespace(fieldName)
                fieldValue = NormalizeWhitespacePreservingLines(fieldValue)
                if fieldName and fieldValue:
                    return fieldName, fieldValue
        return None

    def _DeduplicateFactRecords(
        self,
        factRecords: Sequence[ProductFactRecord],
    ) -> List[ProductFactRecord]:
        deduplicatedRecords: List[ProductFactRecord] = []
        seenFactTexts: set[str] = set()
        for factRecord in factRecords:
            factText = factRecord.ToFactText()
            if factText in seenFactTexts:
                continue
            seenFactTexts.add(factText)
            deduplicatedRecords.append(factRecord)
        return deduplicatedRecords


class LlmProductFactReconstructor:
    """Few-shot LLM을 이용해 table/raw OCR evidence를 상품 input fact로 복원한다."""

    def __init__(
        self,
        runtimeAdapter: Optional[RuntimeAdapter[Any]],
        deterministicReconstructor: DeterministicProductFactReconstructor,
        validator: Optional[ProductFactReconstructionValidator] = None,
    ) -> None:
        self._runtimeAdapter = runtimeAdapter
        self._deterministicReconstructor = deterministicReconstructor
        self._validator = validator or ProductFactReconstructionValidator()

    def Reconstruct(
        self,
        evidencePackage: ProductInputEvidencePackage,
    ) -> ProductFactReconstructionResult:
        deterministicResult = self._deterministicReconstructor.Reconstruct(
            evidencePackage
        )
        if self._runtimeAdapter is None:
            return deterministicResult

        request = self._BuildRequest(evidencePackage, deterministicResult)
        try:
            response = self._runtimeAdapter.Generate(request)
            payload = self._ParseJsonPayload(response.generatedText)
            result = ProductFactReconstructionResult.model_validate(payload)
            result = result.model_copy(
                update={
                    "usedLlmReconstruction": True,
                    "fallbackReason": None,
                    "dictionaryMatches": deterministicResult.dictionaryMatches,
                }
            )
            return self._validator.Validate(result, evidencePackage)
        except (ValueError, ValidationError, RuntimeError) as error:
            return deterministicResult.model_copy(
                update={
                    "warnings": [
                        *deterministicResult.warnings,
                        "llm_reconstruction_failed: {0}".format(error),
                    ],
                    "fallbackReason": "llm_reconstruction_failed",
                }
            )

    def _BuildRequest(
        self,
        evidencePackage: ProductInputEvidencePackage,
        deterministicResult: ProductFactReconstructionResult,
    ) -> LlmRequest:
        contextPayload = {
            "evidence": [
                evidenceRecord.model_dump(mode="json", by_alias=True)
                for evidenceRecord in evidencePackage.records
            ],
            "dictionary_matches": [
                dictionaryMatch.model_dump(mode="json", by_alias=True)
                for dictionaryMatch in deterministicResult.dictionaryMatches
            ],
            "deterministic_facts": [
                factRecord.model_dump(mode="json", by_alias=True)
                for factRecord in deterministicResult.productFacts
            ],
            "few_shot_examples": PRODUCT_FACT_RECONSTRUCTION_FEW_SHOT_EXAMPLES,
        }
        return LlmRequest(
            systemPrompt=PRODUCT_FACT_RECONSTRUCTION_SYSTEM_PROMPT,
            userPrompt="\n".join(
                [
                    "아래 evidence와 dictionary match만 사용해 ProductFactReconstructionResult JSON을 작성하라.",
                    "출력 key는 product_facts, unresolved_facts, conflicts, normalized_fact_texts, warnings, used_llm_reconstruction, fallback_reason, dictionary_matches를 사용하라.",
                    "source_refs에는 evidence_id만 사용하라.",
                    json.dumps(contextPayload, ensure_ascii=False, separators=(",", ":")),
                ]
            ),
            responseFormat=LlmResponseFormat.JSON_OBJECT,
            generationOptions=LlmGenerationOptions(temperature=0.0, maxTokens=2048),
        )

    def _ParseJsonPayload(self, generatedText: str) -> Dict[str, Any]:
        strippedText = generatedText.strip()
        if strippedText == "":
            raise ValueError("empty LLM response")
        try:
            payload = json.loads(strippedText)
        except json.JSONDecodeError:
            startIndex = strippedText.find("{")
            endIndex = strippedText.rfind("}")
            if startIndex < 0 or endIndex <= startIndex:
                raise
            payload = json.loads(strippedText[startIndex : endIndex + 1])
        if not isinstance(payload, dict):
            raise ValueError("LLM reconstruction response must be a JSON object.")
        return payload


class ProductInputReconstructionService:
    """Evidence build, dictionary correction, optional LLM reconstruction을 묶는다."""

    def __init__(
        self,
        dictionaryPath: Optional[str] = None,
        runtimeAdapter: Optional[RuntimeAdapter[Any]] = None,
        fuzzyMinRatio: float = 0.86,
    ) -> None:
        resolvedDictionaryPath = (
            DEFAULT_PRODUCT_INPUT_DICTIONARY_PATH
            if dictionaryPath is None
            else Path(dictionaryPath)
        )
        dictionaryEntries = ProductDictionaryRepository(
            resolvedDictionaryPath,
        ).LoadEntries()
        dictionaryRetriever = ProductDictionaryRetriever(
            dictionaryEntries,
            fuzzyMinRatio=fuzzyMinRatio,
        )
        self._evidenceBuilder = ProductInputEvidenceBuilder()
        self._deterministicReconstructor = DeterministicProductFactReconstructor(
            dictionaryRetriever,
        )
        self._llmReconstructor = LlmProductFactReconstructor(
            runtimeAdapter=runtimeAdapter,
            deterministicReconstructor=self._deterministicReconstructor,
        )

    def ReconstructFromPipelineParts(
        self,
        collectionResult: Any,
        ocrImageResults: Sequence[Any],
        combinedOcrText: str,
    ) -> ProductFactReconstructionResult:
        evidencePackage = self._evidenceBuilder.BuildFromPipelineParts(
            collectionResult=collectionResult,
            ocrImageResults=ocrImageResults,
            combinedOcrText=combinedOcrText,
        )
        return self._llmReconstructor.Reconstruct(evidencePackage)
