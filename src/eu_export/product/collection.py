"""SearchPlan 이후 상품 출처 후보 수집과 fact 추출을 연결하는 pipeline."""

from dataclasses import dataclass, field
from typing import List

from eu_export.product.fact_extractor import (
    ProductClassificationFactPackage,
    ProductFactExtractor,
)
from eu_export.product.fetcher import (
    FetchedProductSource,
    ProductSourceFetchError,
    ProductSourceFetcher,
)
from eu_export.product.plan import SearchPlan
from eu_export.product.ranker import (
    ProductSourceCandidateKind,
    ProductSourceRanker,
    RankedProductSourceCandidate,
)
from eu_export.search import SearchResultItem


@dataclass(frozen=True)
class ProductSourceCollectionResult:
    """SearchPlan 이후 수집 단계의 결과."""

    searchPlan: SearchPlan
    rankedCandidates: List[RankedProductSourceCandidate] = field(default_factory=list)
    fetchedSources: List[FetchedProductSource] = field(default_factory=list)
    factPackages: List[ProductClassificationFactPackage] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def isSuccess(self) -> bool:
        return len(self.factPackages) > 0 and not self.errors


class ProductSourceCollectionPipeline:
    """ranker, fetcher, extractor를 조합해 CN 분류용 상품 fact를 만든다."""

    def __init__(
        self,
        sourceRanker: ProductSourceRanker,
        sourceFetcher: ProductSourceFetcher,
        factExtractor: ProductFactExtractor,
        maxInitialCandidates: int = 5,
        maxProductPagesToFetch: int = 3,
        maxLinksFromCollectionPage: int = 10,
    ) -> None:
        if maxInitialCandidates <= 0:
            raise ValueError("maxInitialCandidates must be greater than 0.")
        if maxProductPagesToFetch <= 0:
            raise ValueError("maxProductPagesToFetch must be greater than 0.")
        if maxLinksFromCollectionPage <= 0:
            raise ValueError("maxLinksFromCollectionPage must be greater than 0.")

        self._sourceRanker = sourceRanker
        self._sourceFetcher = sourceFetcher
        self._factExtractor = factExtractor
        self._maxInitialCandidates = maxInitialCandidates
        self._maxProductPagesToFetch = maxProductPagesToFetch
        self._maxLinksFromCollectionPage = maxLinksFromCollectionPage

    def Collect(
        self,
        searchPlan: SearchPlan,
        resultItems: List[SearchResultItem],
    ) -> ProductSourceCollectionResult:
        rankedCandidates = self._BuildInitialCandidates(searchPlan, resultItems)
        allRankedCandidates = list(rankedCandidates)
        fetchedSources: List[FetchedProductSource] = []
        factPackages: List[ProductClassificationFactPackage] = []
        errors: List[str] = []
        queuedProductCandidates = list(rankedCandidates)
        seenUrls: set[str] = set()

        while queuedProductCandidates and (
            len(factPackages) < self._maxProductPagesToFetch
        ):
            candidate = queuedProductCandidates.pop(0)
            if candidate.productPageUrl in seenUrls:
                continue
            seenUrls.add(candidate.productPageUrl)

            try:
                fetchedSource = self._sourceFetcher.FetchUrl(candidate.productPageUrl)
            except ProductSourceFetchError as error:
                errors.append(
                    "{0}: {1}".format(candidate.productPageUrl, error)
                )
                continue

            fetchedSources.append(fetchedSource)

            if candidate.candidateKind == ProductSourceCandidateKind.COLLECTION_PAGE:
                linkCandidates = self._sourceRanker.RankFetchedLinks(
                    searchPlan,
                    fetchedSource.productPageUrl,
                    fetchedSource.linkUrls,
                    maxCandidates=self._maxLinksFromCollectionPage,
                )
                allRankedCandidates = self._sourceRanker.MergeCandidates(
                    [allRankedCandidates, linkCandidates],
                    maxCandidates=(
                        self._maxInitialCandidates
                        + self._maxLinksFromCollectionPage
                    ),
                )
                queuedProductCandidates.extend(linkCandidates)
                queuedProductCandidates = self._sourceRanker.MergeCandidates(
                    [queuedProductCandidates],
                    maxCandidates=self._maxLinksFromCollectionPage,
                )
                continue

            factPackages.append(
                self._factExtractor.Extract(fetchedSource, candidate)
            )

        return ProductSourceCollectionResult(
            searchPlan=searchPlan,
            rankedCandidates=allRankedCandidates,
            fetchedSources=fetchedSources,
            factPackages=factPackages,
            errors=errors,
        )

    def _BuildInitialCandidates(
        self,
        searchPlan: SearchPlan,
        resultItems: List[SearchResultItem],
    ) -> List[RankedProductSourceCandidate]:
        seedCandidates = self._sourceRanker.BuildSeedCandidates(searchPlan)
        searchResultCandidates = self._sourceRanker.RankSearchResults(
            searchPlan,
            resultItems,
            maxCandidates=self._maxInitialCandidates,
        )

        return self._sourceRanker.MergeCandidates(
            [seedCandidates, searchResultCandidates],
            maxCandidates=self._maxInitialCandidates,
        )
