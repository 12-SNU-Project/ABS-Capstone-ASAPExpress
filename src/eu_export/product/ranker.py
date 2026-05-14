"""SearchPlan과 검색 결과를 바탕으로 상품 출처 URL 후보를 정렬한다."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eu_export.product.fetcher import DEFAULT_BEAUTY_KURLY_SCROLL_URL
from eu_export.product.plan import SearchPlan
from eu_export.product.query import ProductDomainHint, QueryType
from eu_export.product.source import (
    ExtractHostName,
    ProductSourcePolicy,
    ProductSourceRole,
)
from eu_export.search import SearchResultItem
from eu_export.utils import NormalizeWhitespace


class ProductSourceCandidateKind(str):
    """상품 후보 URL의 용도 구분."""

    PRODUCT_PAGE = "product_page"
    COLLECTION_PAGE = "collection_page"


@dataclass(frozen=True)
class RankedProductSourceCandidate:
    """fetch 대상 URL과 우선순위 점수."""

    productPageUrl: str
    sourceProvider: str
    sourceRole: ProductSourceRole
    productDomainHint: ProductDomainHint
    candidateKind: str
    rankScore: float
    rankReasons: List[str] = field(default_factory=list)
    rawSearchTitle: Optional[str] = None
    rawSearchSnippet: Optional[str] = None
    rawCandidateData: Dict[str, Any] = field(default_factory=dict)

    def ToDict(self) -> Dict[str, Any]:
        return {
            "product_page_url": self.productPageUrl,
            "source_provider": self.sourceProvider,
            "source_role": self.sourceRole.value,
            "product_domain_hint": self.productDomainHint.value,
            "candidate_kind": self.candidateKind,
            "rank_score": self.rankScore,
            "rank_reasons": list(self.rankReasons),
            "raw_search_title": self.rawSearchTitle,
            "raw_search_snippet": self.rawSearchSnippet,
            "raw_candidate_data": dict(self.rawCandidateData),
        }


class ProductSourceRanker:
    """검색 결과와 컬렉션 링크 중 상품 상세 페이지 후보를 우선순위화한다."""

    def __init__(
        self,
        sourcePolicy: ProductSourcePolicy,
        defaultBeautyKurlyScrollUrl: str = DEFAULT_BEAUTY_KURLY_SCROLL_URL,
    ) -> None:
        self._sourcePolicy = sourcePolicy
        self._defaultBeautyKurlyScrollUrl = defaultBeautyKurlyScrollUrl

    def BuildSeedCandidates(
        self,
        searchPlan: SearchPlan,
    ) -> List[RankedProductSourceCandidate]:
        """SearchPlan만으로 바로 접근할 수 있는 URL 후보를 만든다."""

        candidates: List[RankedProductSourceCandidate] = []
        if searchPlan.queryType == QueryType.URL:
            targetUrl = searchPlan.searchQueries[0] if searchPlan.searchQueries else (
                searchPlan.normalizedQuery
            )
            candidates.append(
                self._BuildUrlCandidate(
                    url=targetUrl,
                    searchPlan=searchPlan,
                    candidateKind=ProductSourceCandidateKind.PRODUCT_PAGE,
                    baseScore=100.0,
                    rankReasons=["user provided a direct URL"],
                )
            )
            return candidates

        if self._ShouldUseBeautyKurlySeed(searchPlan):
            candidates.append(
                self._BuildUrlCandidate(
                    url=self._defaultBeautyKurlyScrollUrl,
                    searchPlan=searchPlan,
                    candidateKind=ProductSourceCandidateKind.COLLECTION_PAGE,
                    baseScore=70.0,
                    rankReasons=["default Beauty Kurly collection seed"],
                )
            )

        return candidates

    def RankSearchResults(
        self,
        searchPlan: SearchPlan,
        resultItems: List[SearchResultItem],
        maxCandidates: int = 10,
    ) -> List[RankedProductSourceCandidate]:
        if maxCandidates <= 0:
            return []

        candidates: List[RankedProductSourceCandidate] = []
        for resultItem in resultItems:
            candidateKind = self._InferCandidateKind(resultItem.url)
            candidate = self._BuildUrlCandidate(
                url=resultItem.url,
                searchPlan=searchPlan,
                candidateKind=candidateKind,
                baseScore=self._BuildSearchResultBaseScore(resultItem),
                rankReasons=[
                    "search result rank {0}".format(resultItem.rank),
                ],
                rawSearchTitle=resultItem.title,
                rawSearchSnippet=resultItem.snippet,
                rawCandidateData={
                    "search_provider": resultItem.sourceProvider,
                    "query": resultItem.query,
                    "rank": resultItem.rank,
                    "raw_data": dict(resultItem.rawData),
                },
            )
            candidates.append(candidate)

        return self._SortAndLimitCandidates(candidates, maxCandidates)

    def RankFetchedLinks(
        self,
        searchPlan: SearchPlan,
        sourceUrl: str,
        linkUrls: List[str],
        maxCandidates: int = 10,
    ) -> List[RankedProductSourceCandidate]:
        if maxCandidates <= 0:
            return []

        candidates: List[RankedProductSourceCandidate] = []
        seenUrls: set[str] = set()
        for linkUrl in linkUrls:
            normalizedUrl = linkUrl.strip()
            if normalizedUrl == "" or normalizedUrl in seenUrls:
                continue
            seenUrls.add(normalizedUrl)
            candidateKind = self._InferCandidateKind(normalizedUrl)
            if candidateKind != ProductSourceCandidateKind.PRODUCT_PAGE:
                continue

            candidates.append(
                self._BuildUrlCandidate(
                    url=normalizedUrl,
                    searchPlan=searchPlan,
                    candidateKind=candidateKind,
                    baseScore=50.0,
                    rankReasons=["product link discovered from {0}".format(sourceUrl)],
                    rawCandidateData={"source_url": sourceUrl},
                )
            )

        return self._SortAndLimitCandidates(candidates, maxCandidates)

    def MergeCandidates(
        self,
        candidateGroups: List[List[RankedProductSourceCandidate]],
        maxCandidates: int = 10,
    ) -> List[RankedProductSourceCandidate]:
        candidatesByUrl: Dict[str, RankedProductSourceCandidate] = {}
        for candidateGroup in candidateGroups:
            for candidate in candidateGroup:
                currentCandidate = candidatesByUrl.get(candidate.productPageUrl)
                if (
                    currentCandidate is None
                    or candidate.rankScore > currentCandidate.rankScore
                ):
                    candidatesByUrl[candidate.productPageUrl] = candidate

        return self._SortAndLimitCandidates(
            list(candidatesByUrl.values()),
            maxCandidates,
        )

    def _BuildUrlCandidate(
        self,
        url: str,
        searchPlan: SearchPlan,
        candidateKind: str,
        baseScore: float,
        rankReasons: List[str],
        rawSearchTitle: Optional[str] = None,
        rawSearchSnippet: Optional[str] = None,
        rawCandidateData: Optional[Dict[str, Any]] = None,
    ) -> RankedProductSourceCandidate:
        normalizedUrl = self._NormalizeUrl(url)
        sourceProvider, sourceRole, productDomainHint = self._ResolveSource(
            normalizedUrl,
        )
        rankScore = baseScore
        reasons = list(rankReasons)

        if sourceRole != ProductSourceRole.UNKNOWN:
            rankScore += 20.0
            reasons.append("source domain is mapped by product source policy")
        else:
            rankScore -= 20.0
            reasons.append("source domain is not mapped by product source policy")

        if self._IsKurlyUrl(normalizedUrl):
            rankScore += 15.0
            reasons.append("Kurly source candidate")

        if "/goods/" in normalizedUrl:
            rankScore += 25.0
            reasons.append("URL pattern looks like a product detail page")

        if self._LooksBeautyKurlyUrl(normalizedUrl):
            rankScore += 15.0
            reasons.append("URL pattern looks related to Beauty Kurly")
            if productDomainHint in (
                ProductDomainHint.UNKNOWN,
                ProductDomainHint.AMBIGUOUS,
            ):
                productDomainHint = ProductDomainHint.COSMETICS

        if productDomainHint in searchPlan.searchProductDomains:
            rankScore += 15.0
            reasons.append("candidate domain matches SearchPlan product domain")

        rankScore += self._BuildQueryOverlapScore(
            searchPlan,
            rawSearchTitle,
            rawSearchSnippet,
            reasons,
        )

        return RankedProductSourceCandidate(
            productPageUrl=normalizedUrl,
            sourceProvider=sourceProvider,
            sourceRole=sourceRole,
            productDomainHint=productDomainHint,
            candidateKind=candidateKind,
            rankScore=rankScore,
            rankReasons=reasons,
            rawSearchTitle=rawSearchTitle,
            rawSearchSnippet=rawSearchSnippet,
            rawCandidateData=dict(rawCandidateData or {}),
        )

    def _ResolveSource(
        self,
        url: str,
    ) -> tuple[str, ProductSourceRole, ProductDomainHint]:
        domainRule = self._sourcePolicy.Resolve(url)
        if domainRule is None:
            return (
                ExtractHostName(url),
                ProductSourceRole.UNKNOWN,
                ProductDomainHint.UNKNOWN,
            )

        return (
            domainRule.sourceProvider,
            domainRule.sourceRole,
            domainRule.productDomainHint,
        )

    def _BuildSearchResultBaseScore(self, resultItem: SearchResultItem) -> float:
        if resultItem.rank <= 0:
            return 40.0
        return max(20.0, 45.0 - float(resultItem.rank))

    def _BuildQueryOverlapScore(
        self,
        searchPlan: SearchPlan,
        rawSearchTitle: Optional[str],
        rawSearchSnippet: Optional[str],
        reasons: List[str],
    ) -> float:
        candidateText = NormalizeWhitespace(
            " ".join(
                value
                for value in [rawSearchTitle, rawSearchSnippet]
                if isinstance(value, str)
            )
        ).lower()
        if candidateText == "":
            return 0.0

        searchTerms = [
            term.lower()
            for searchQuery in searchPlan.searchQueries
            for term in searchQuery.split()
            if len(term.strip()) >= 2
        ]
        matchedTerms = sorted({term for term in searchTerms if term in candidateText})
        if not matchedTerms:
            return 0.0

        reasons.append(
            "search query terms matched: {0}".format(", ".join(matchedTerms))
        )
        return min(20.0, float(len(matchedTerms)) * 4.0)

    def _ShouldUseBeautyKurlySeed(self, searchPlan: SearchPlan) -> bool:
        return (
            searchPlan.productDomainHint == ProductDomainHint.COSMETICS
            or ProductDomainHint.COSMETICS in searchPlan.searchProductDomains
        )

    def _InferCandidateKind(self, url: str) -> str:
        normalizedUrl = url.lower()
        if "/goods/" in normalizedUrl:
            return ProductSourceCandidateKind.PRODUCT_PAGE
        return ProductSourceCandidateKind.COLLECTION_PAGE

    def _IsKurlyUrl(self, url: str) -> bool:
        return ExtractHostName(url).endswith("kurly.com")

    def _LooksBeautyKurlyUrl(self, url: str) -> bool:
        loweredUrl = url.lower()
        return "beauty" in loweredUrl or "beauty-kurly" in loweredUrl

    def _NormalizeUrl(self, url: str) -> str:
        normalizedUrl = url.strip()
        if normalizedUrl.startswith("http://") or normalizedUrl.startswith(
            "https://",
        ):
            return normalizedUrl
        return "https://" + normalizedUrl

    def _SortAndLimitCandidates(
        self,
        candidates: List[RankedProductSourceCandidate],
        maxCandidates: int,
    ) -> List[RankedProductSourceCandidate]:
        return sorted(
            candidates,
            key=lambda candidate: candidate.rankScore,
            reverse=True,
        )[:maxCandidates]
