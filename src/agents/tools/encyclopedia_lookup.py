"""Wikipedia encyclopedia evidence lookup."""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from agents.pipeline_dto import EncyclopediaEntryDto, EncyclopediaEvidenceSet


WIKIPEDIA_SEARCH_ENDPOINT = "https://en.wikipedia.org/w/rest.php/v1/search/title"
WIKIPEDIA_SUMMARY_ENDPOINT = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
KO_WIKIPEDIA_SEARCH_ENDPOINT = "https://ko.wikipedia.org/w/rest.php/v1/search/title"
KO_WIKIPEDIA_LANG_LINK_ENDPOINT = "https://ko.wikipedia.org/w/api.php"
WIKI_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ASAPExpress/1.0 (+https://github.com/)",
}
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
HANGUL_RE = re.compile(r"[가-힣]")
FOOD_RELATED_HINT_RE = re.compile(
    r"\b("
    r"food|edible|beverage|juice|rice|seafood|fish|shrimp|prawn|octopus|squid|meat|beef|pork|"
    r"vegetable|fruit|noodle|noodles|pasta|bread|soup|stew|broth|sauce|seasoning|sauce|fried|frozen|"
    r"raw|cooked|grocery|ingredient|recipe|korean|chicken|lamb|cheese|milk|egg|dairy|meat|tuna|salmon|"
    r"만두|떡볶|우동|라면|면|국|국물|조림|조리|냉동|냉장|생선|어류|새우|주꾸미|쭈꾸미"
    r")\b",
    re.I,
)
OFFTOPIC_RE = re.compile(
    r"\b("
    r"tv|television|drama|series|film|movie|anime|cartoon|comic|manhwa|manga|music|album|song|singer|"
    r"musician|artist|band|character|bus|station|village|city|river|mountain|person|actor|actress|writer|"
    r"place|company|organization|church|university|school|airport|hotel|restaurant|brand|logo|franchise"
    r")\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class WikipediaSearchResult:
    title: str
    description: str
    snippet: str
    link: str


def LookupEncyclopediaEvidence(
    *,
    encyclopediaEvidenceId: str,
    productId: str,
    query: str,
    display: int = 3,
    timeoutSeconds: float = 10.0,
) -> EncyclopediaEvidenceSet:
    normalizedQuery = CleanEncyclopediaQuery(query)
    if not normalizedQuery:
        return EncyclopediaEvidenceSet(
            encyclopediaEvidenceId=encyclopediaEvidenceId,
            productId=productId,
            query=query.strip(),
            configured=True,
            qualityStatus="no_query",
            qualityReasons=("empty_query",),
        )

    rows: list[WikipediaSearchResult] = []
    relevanceRejectedCount = 0
    searchError = ""
    qualityStatus = "raw_entries"
    qualityReasons = ("raw_not_routing_input",)
    # Restored backup candidate fallback: brand/quantity-stripped full query
    # first, then trailing dish-name suffixes ("압구정낙지 낙지 볶음" -> "낙지 볶음").
    for candidate in _QueryCandidates(normalizedQuery):
        try:
            rows, qualityStatus, qualityReasons = _lookup_candidate(
                candidate,
                limit=display,
                timeoutSeconds=timeoutSeconds,
            )
            filteredRows = []
            for row in rows:
                isRelevant, _ = _IsWikipediaRowRelevant(normalizedQuery, row)
                if isRelevant:
                    filteredRows.append(row)
                else:
                    relevanceRejectedCount += 1
            rows = filteredRows
        except Exception as exc:  # noqa: BLE001 — keep lookup tolerant
            searchError = f"{type(exc).__name__}: {exc}"
            continue
        if rows:
            normalizedQuery = candidate
            searchError = ""
            break

    if not rows and searchError:
        return EncyclopediaEvidenceSet(
            encyclopediaEvidenceId=encyclopediaEvidenceId,
            productId=productId,
            query=normalizedQuery,
            configured=True,
            qualityStatus="error",
            qualityReasons=("lookup_error",),
            error=searchError,
        )

    if not rows:
        if relevanceRejectedCount > 0:
            return EncyclopediaEvidenceSet(
                encyclopediaEvidenceId=encyclopediaEvidenceId,
                productId=productId,
                query=normalizedQuery,
                configured=True,
                qualityStatus="no_relevant_result",
                qualityReasons=("relevance_guard_failed",),
                entries=(),
            )
        return EncyclopediaEvidenceSet(
            encyclopediaEvidenceId=encyclopediaEvidenceId,
            productId=productId,
            query=normalizedQuery,
            configured=True,
            qualityStatus="no_result",
            qualityReasons=("no_items",),
        )

    return EncyclopediaEvidenceSet(
        encyclopediaEvidenceId=encyclopediaEvidenceId,
        productId=productId,
        query=normalizedQuery,
        configured=True,
        entries=tuple(
            EncyclopediaEntryDto(
                title=row.title,
                description=row.snippet,
                link=row.link,
                contentHash=_HashEntry(row.title, row.description, row.snippet, row.link),
            )
            for row in rows
        ),
        qualityStatus=qualityStatus,
        qualityReasons=qualityReasons,
    )


def _IsWikipediaRowRelevant(query: str, row: WikipediaSearchResult) -> tuple[bool, str]:
    queryText = str(query or "").strip()
    candidateText = f"{row.title} {row.description} {row.snippet}"
    if not queryText:
        return False, "empty_query"

    if OFFTOPIC_RE.search(candidateText) and not FOOD_RELATED_HINT_RE.search(candidateText):
        return False, "offtopic_pattern"

    if _ContainsHangul(queryText):
        if _HasKoreanOverlap(queryText, candidateText):
            return True, "query_overlap"
        if FOOD_RELATED_HINT_RE.search(queryText) and FOOD_RELATED_HINT_RE.search(candidateText):
            return True, "food_signal_overlap"
        return False, "food_signal_mismatch"
    if _HasOverlap(queryText, candidateText):
        return True, "token_overlap"
    if FOOD_RELATED_HINT_RE.search(candidateText):
        return True, "food_signal_fallback"
    return False, "generic_non_food"


def _HasKoreanOverlap(left: str, right: str) -> bool:
    leftTokens = _Tokenize(left)
    rightTokens = _Tokenize(right)
    return bool(leftTokens.intersection(rightTokens))


def _HasOverlap(left: str, right: str) -> bool:
    leftTokens = _Tokenize(left)
    rightTokens = _Tokenize(right)
    return bool(leftTokens.intersection(rightTokens))


def _Tokenize(text: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-zA-Z가-힣]", " ", text.lower())
    return {token for token in normalized.split() if len(token) >= 2}


def CleanEncyclopediaQuery(value: str) -> str:
    """Strip brand/quantity/marketing noise from a product name before lookup.

    Restored from the pre-merge backup (_clean_encyclopedia_query): raw product
    names hijack encyclopedia search ("전주 베테랑 칼국수" -> Jeonju the city).
    """
    text = re.sub(r"\[[^\]]+\]", " ", str(value or ""))
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:g|kg|ml|l|개입|팩|종|인분)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:택\s*1|택1|냉동|냉장|상온|간편|프리미엄)\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip(" -_/|")


def _QueryCandidates(cleanedQuery: str, *, limit: int = 4) -> tuple[str, ...]:
    """Cleaned query first, then trailing-token suffixes (dish name is usually last)."""
    tokens = [token for token in cleanedQuery.split() if len(token) >= 2]
    candidates: list[str] = [cleanedQuery]
    for start in range(1, len(tokens)):
        suffix = " ".join(tokens[start:])
        if suffix and suffix not in candidates:
            candidates.append(suffix)
        if len(candidates) >= limit:
            break
    return tuple(candidates)


def _lookup_candidate(
    query: str,
    *,
    limit: int,
    timeoutSeconds: float,
) -> tuple[list[WikipediaSearchResult], str, tuple[str, ...]]:
    if _ContainsHangul(query):
        translatedRows = _search_korean_wikipedia_as_english(
            query,
            limit=limit,
            timeoutSeconds=timeoutSeconds,
        )
        if translatedRows:
            return (
                translatedRows,
                "translated_entries",
                ("ko_wikipedia_langlink", "raw_not_routing_input"),
            )

    rows = _search_wikipedia(query, limit=limit, timeoutSeconds=timeoutSeconds)
    return rows, "raw_entries", ("raw_not_routing_input",)


def _search_wikipedia(
    query: str,
    *,
    limit: int,
    timeoutSeconds: float,
) -> list[WikipediaSearchResult]:
    request = urllib.request.Request(
        _BuildSearchUrl(query, limit=limit),
        headers=WIKI_REQUEST_HEADERS,
    )
    rows: list[WikipediaSearchResult] = []
    with urllib.request.urlopen(request, timeout=timeoutSeconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    for rawItem in _ReadSearchItems(payload):
        if not isinstance(rawItem, dict):
            continue
        title = _StripMarkup(str(rawItem.get("title") or "")).strip()
        if not title:
            continue
        description = _StripMarkup(str(rawItem.get("description") or "")).strip()
        snippet = _StripMarkup(str(rawItem.get("excerpt") or description or "")).strip()
        summary = _fetch_summary_snippet(title, timeoutSeconds=timeoutSeconds)
        if summary:
            snippet = summary
        link = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        rows.append(
            WikipediaSearchResult(
                title=title,
                description=description,
                snippet=snippet,
                link=link,
            ),
        )
    return rows


def _search_korean_wikipedia_as_english(
    query: str,
    *,
    limit: int,
    timeoutSeconds: float,
) -> list[WikipediaSearchResult]:
    request = urllib.request.Request(
        _BuildSearchUrl(
            query,
            limit=limit,
            endpoint=KO_WIKIPEDIA_SEARCH_ENDPOINT,
        ),
        headers=WIKI_REQUEST_HEADERS,
    )
    with urllib.request.urlopen(request, timeout=timeoutSeconds) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rows: list[WikipediaSearchResult] = []
    seenTitles: set[str] = set()
    for rawItem in _ReadSearchItems(payload):
        koreanTitle = _StripMarkup(str(rawItem.get("title") or "")).strip()
        if not koreanTitle:
            continue
        koreanDescription = _StripMarkup(
            str(rawItem.get("description") or rawItem.get("excerpt") or ""),
        ).strip()
        englishTitle = _fetch_english_langlink(
            koreanTitle,
            timeoutSeconds=timeoutSeconds,
        )
        if not englishTitle or englishTitle in seenTitles:
            continue
        seenTitles.add(englishTitle)
        snippet = _fetch_summary_snippet(
            englishTitle,
            timeoutSeconds=timeoutSeconds,
        )
        link = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(englishTitle.replace(' ', '_'))}"
        rows.append(
            WikipediaSearchResult(
                title=englishTitle,
                description=" ".join(
                    text
                    for text in (koreanTitle, koreanDescription)
                    if text
                ),
                snippet=snippet or englishTitle,
                link=link,
            ),
        )
    return rows


def _fetch_english_langlink(title: str, *, timeoutSeconds: float) -> str:
    request = urllib.request.Request(
        KO_WIKIPEDIA_LANG_LINK_ENDPOINT
        + "?"
        + urllib.parse.urlencode(
            {
                "action": "query",
                "prop": "langlinks",
                "titles": title,
                "lllang": "en",
                "lllimit": 1,
                "format": "json",
                "formatversion": 2,
            },
        ),
        headers=WIKI_REQUEST_HEADERS,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeoutSeconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    queryPayload = payload.get("query")
    if not isinstance(queryPayload, dict):
        return ""
    pages = queryPayload.get("pages")
    if not isinstance(pages, list):
        return ""
    for page in pages:
        if not isinstance(page, dict):
            continue
        langlinks = page.get("langlinks")
        if not isinstance(langlinks, list):
            continue
        for langlink in langlinks:
            if not isinstance(langlink, dict):
                continue
            if langlink.get("lang") == "en":
                return str(langlink.get("title") or langlink.get("*") or "").strip()
    return ""


def _fetch_summary_snippet(title: str, *, timeoutSeconds: float) -> str:
    request = urllib.request.Request(
        WIKIPEDIA_SUMMARY_ENDPOINT.format(title=urllib.parse.quote(title)),
        headers=WIKI_REQUEST_HEADERS,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeoutSeconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            return ""
        extract = str(payload.get("extract") or "").strip()
        if extract:
            return _StripMarkup(extract)
    except Exception:
        return ""
    return ""


def _ReadSearchItems(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        return []
    rawItems = payload.get("pages")
    if isinstance(rawItems, dict):
        # Some clients return {pages: {"results": [...]}}
        candidates = rawItems.get("results")
        if isinstance(candidates, list):
            return [
                item
                for item in candidates
                if isinstance(item, dict)
            ]
    if isinstance(rawItems, list):
        return [item for item in rawItems if isinstance(item, dict)]
    fallback = payload.get("results")
    return [item for item in (fallback if isinstance(fallback, list) else []) if isinstance(item, dict)]


def _BuildSearchUrl(
    query: str,
    *,
    limit: int,
    endpoint: str = WIKIPEDIA_SEARCH_ENDPOINT,
) -> str:
    return endpoint + "?" + urllib.parse.urlencode(
        {
            "q": query,
            "limit": max(1, min(limit, 10)),
            "format": "json",
        },
    )


def _ContainsHangul(value: str) -> bool:
    return HANGUL_RE.search(value) is not None


def _StripMarkup(markup: str) -> str:
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub("", markup))).strip()


def _HashEntry(title: str, description: str, snippet: str, link: str) -> str:
    raw = "\n".join([title, description, snippet, link])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
