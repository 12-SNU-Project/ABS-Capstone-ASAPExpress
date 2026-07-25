"""Deterministic database dictionary retrieval for product input correction."""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from bussiness_logic.utils import NormalizeWhiteSpace
from bussiness_logic.core.runtime_asset_repository import (
    LoadProductInputDictionary,
)


DEFAULT_FUZZY_MIN_RATIO = 0.86
DEFAULT_MIN_FUZZY_CHARACTERS = 4
DEFAULT_AMBIGUOUS_RATIO_MARGIN = 0.08


class ProductDictionaryEntry(BaseModel):
    """표준 상품 입력 용어 사전의 단일 record."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    termId: str = Field(alias="term_id")
    canonicalName: str = Field(alias="canonical_name")
    termType: str = Field(alias="term_type")
    aliases: List[str] = Field(default_factory=list)
    sourceName: str = Field(default="", alias="source_name")
    sourceId: str = Field(default="", alias="source_id")
    sourceUrl: str = Field(default="", alias="source_url")
    updatedAt: str = Field(default="", alias="updated_at")

    def BuildSourceRef(self) -> str:
        return "{0}:{1}:{2}".format(
            self.sourceName or "dictionary",
            self.sourceId or "unknown",
            self.termId,
        )


class ProductDictionaryMatch(BaseModel):
    """OCR span과 표준 사전 entry의 매칭 결과."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    rawText: str = Field(alias="raw_text")
    matchedText: str = Field(alias="matched_text")
    canonicalName: str = Field(alias="canonical_name")
    termType: str = Field(alias="term_type")
    matchType: str = Field(alias="match_type")
    sourceRef: str = Field(alias="source_ref")
    correctionAction: str = Field(alias="correction_action")


class ProductDictionaryRepository:
    """Database-backed standard product input dictionary."""

    def LoadEntries(self) -> List[ProductDictionaryEntry]:
        entries: List[ProductDictionaryEntry] = []
        for row in LoadProductInputDictionary():
            aliasesValue = row.get("aliases")
            if isinstance(aliasesValue, list):
                aliases = aliasesValue
            else:
                aliases = str(aliasesValue or "").split("|")
            termId = str(row.get("term_id") or "").strip()
            canonicalName = str(row.get("canonical_name") or "").strip()
            if not termId or not canonicalName:
                continue
            entries.append(
                ProductDictionaryEntry(
                    term_id=termId,
                    canonical_name=canonicalName,
                    term_type=str(row.get("term_type") or "").strip(),
                    aliases=[
                        NormalizeWhiteSpace(str(alias))
                        for alias in aliases
                        if NormalizeWhiteSpace(str(alias))
                    ],
                    source_name=str(row.get("source_name") or "").strip(),
                    source_id=str(row.get("source_id") or "").strip(),
                    source_url=str(row.get("source_url") or "").strip(),
                    updated_at=str(row.get("updated_at") or "").strip(),
                )
            )
        return entries


class ProductDictionaryRetriever:
    """OCR text span을 표준 dictionary에 deterministic하게 매칭한다."""

    def __init__(
        self,
        entries: Sequence[ProductDictionaryEntry],
        fuzzyMinRatio: float = DEFAULT_FUZZY_MIN_RATIO,
        minFuzzyCharacters: int = DEFAULT_MIN_FUZZY_CHARACTERS,
        ambiguousRatioMargin: float = DEFAULT_AMBIGUOUS_RATIO_MARGIN,
        maxCandidateCount: int = 5,
    ) -> None:
        self._entries = list(entries)
        self._fuzzyMinRatio = fuzzyMinRatio
        self._minFuzzyCharacters = max(1, minFuzzyCharacters)
        self._ambiguousRatioMargin = max(0.0, ambiguousRatioMargin)
        self._maxCandidateCount = max(1, maxCandidateCount)
        self._lookup: Dict[str, Tuple[ProductDictionaryEntry, str]] = {}
        self._compactLookup: Dict[str, Tuple[ProductDictionaryEntry, str]] = {}
        self._fuzzyChoices: List[Tuple[str, ProductDictionaryEntry]] = []
        self._BuildIndexes()

    def FindMatches(self, texts: Sequence[str]) -> List[ProductDictionaryMatch]:
        matches: List[ProductDictionaryMatch] = []
        seenKeys: set[tuple[str, str, str]] = set()
        for text in texts:
            for span in self._BuildCandidateSpans(text):
                spanMatches = self.FindMatchesForText(span)
                for match in spanMatches:
                    matchKey = (
                        match.matchedText,
                        match.canonicalName,
                        match.matchType,
                    )
                    if matchKey in seenKeys:
                        continue
                    seenKeys.add(matchKey)
                    matches.append(match)
        return matches

    def FindMatchesForText(self, text: str) -> List[ProductDictionaryMatch]:
        normalizedText = NormalizeWhiteSpace(text)
        if normalizedText == "":
            return []

        lookupValue = normalizedText.lower()
        compactValue = re.sub(r"[\s\W_]+", "", normalizedText.lower())

        exactEntry = self._lookup.get(lookupValue)
        if exactEntry is not None:
            entry, matchType = exactEntry
            return [
                ProductDictionaryMatch(
                    rawText=normalizedText,
                    matchedText=normalizedText,
                    canonicalName=entry.canonicalName,
                    termType=entry.termType,
                    matchType=matchType,
                    sourceRef=entry.BuildSourceRef(),
                    correctionAction="auto_corrected",
                )
            ]

        compactEntry = self._compactLookup.get(compactValue)
        if compactEntry is not None:
            entry, matchType = compactEntry
            return [
                ProductDictionaryMatch(
                    rawText=normalizedText,
                    matchedText=normalizedText,
                    canonicalName=entry.canonicalName,
                    termType=entry.termType,
                    matchType="compact" if matchType == "exact" else matchType,
                    sourceRef=entry.BuildSourceRef(),
                    correctionAction="auto_corrected",
                )
            ]

        if len(compactValue) < self._minFuzzyCharacters:
            return []

        bestRatioByTermId: Dict[str, Tuple[float, ProductDictionaryEntry]] = {}
        for choice, entry in self._fuzzyChoices:
            ratio = float(fuzz.ratio(compactValue, choice)) / 100.0
            currentBest = bestRatioByTermId.get(entry.termId)
            if currentBest is None or ratio > currentBest[0]:
                bestRatioByTermId[entry.termId] = (ratio, entry)

        fuzzyCandidates = sorted(
            bestRatioByTermId.values(),
            key=lambda candidate: candidate[0],
            reverse=True,
        )[: self._maxCandidateCount]
        if not fuzzyCandidates:
            return []

        topRatio, topEntry = fuzzyCandidates[0]
        if topRatio < self._fuzzyMinRatio:
            return []

        secondRatio = fuzzyCandidates[1][0] if len(fuzzyCandidates) >= 2 else 0.0
        correctionAction = (
            "auto_corrected"
            if topRatio - secondRatio >= self._ambiguousRatioMargin
            else "candidate_only"
        )
        return [
            ProductDictionaryMatch(
                rawText=normalizedText,
                matchedText=normalizedText,
                canonicalName=topEntry.canonicalName,
                termType=topEntry.termType,
                matchType="fuzzy",
                sourceRef=topEntry.BuildSourceRef(),
                correctionAction=correctionAction,
            )
        ]

    def _BuildIndexes(self) -> None:
        for entry in self._entries:
            self._IndexTerm(entry, entry.canonicalName, "exact")
            for alias in entry.aliases:
                self._IndexTerm(entry, alias, "alias")

    def _IndexTerm(
        self,
        entry: ProductDictionaryEntry,
        value: str,
        matchType: str,
    ) -> None:
        normalizedValue = NormalizeWhiteSpace(value).lower()
        compactValue = re.sub(r"[\s\W_]+", "", normalizedValue)
        if normalizedValue:
            self._lookup.setdefault(normalizedValue, (entry, matchType))
        if compactValue:
            self._compactLookup.setdefault(compactValue, (entry, matchType))
            self._fuzzyChoices.append((compactValue, entry))

    def _BuildCandidateSpans(self, text: str) -> List[str]:
        normalizedText = NormalizeWhiteSpace(text)
        if normalizedText == "":
            return []
        spans = [normalizedText]
        for span in re.split(r"[,/|;:：·()\[\]\n\r]+", normalizedText):
            normalizedSpan = NormalizeWhiteSpace(span)
            if normalizedSpan:
                spans.append(normalizedSpan)
        spans.extend(re.findall(r"[0-9A-Za-z가-힣_]+", normalizedText))
        return list(dict.fromkeys(spans))
