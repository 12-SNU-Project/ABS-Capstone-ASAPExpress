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
WIKI_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ASAPExpress/1.0 (+https://github.com/)",
}
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


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
    searchError = ""
    # Restored backup candidate fallback: brand/quantity-stripped full query
    # first, then trailing dish-name suffixes ("압구정낙지 낙지 볶음" -> "낙지 볶음").
    for candidate in _QueryCandidates(normalizedQuery):
        try:
            rows = list(_search_wikipedia(candidate, limit=display, timeoutSeconds=timeoutSeconds))
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
        qualityStatus="raw_entries",
        qualityReasons=("raw_not_routing_input",),
    )


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


_KOREAN_RE = re.compile(r"[가-힣]")
KO_WIKIPEDIA_SEARCH_ENDPOINT = "https://ko.wikipedia.org/w/rest.php/v1/search/title"
KO_WIKIPEDIA_ACTION_ENDPOINT = "https://ko.wikipedia.org/w/api.php"


def _fetch_en_langlink(koTitle: str, *, timeoutSeconds: float) -> str:
    """ko.wikipedia article title -> its English article title ("" if none)."""
    url = KO_WIKIPEDIA_ACTION_ENDPOINT + "?" + urllib.parse.urlencode({
        "action": "query", "titles": koTitle, "prop": "langlinks",
        "lllang": "en", "format": "json", "redirects": 1,
    })
    request = urllib.request.Request(url, headers=WIKI_REQUEST_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeoutSeconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        pages = payload.get("query", {}).get("pages", {}) if isinstance(payload, dict) else {}
        for page in pages.values():
            langlinks = page.get("langlinks") if isinstance(page, dict) else None
            if isinstance(langlinks, list) and langlinks:
                return str(langlinks[0].get("*") or "").strip()
    except Exception:  # noqa: BLE001 — langlink is best-effort
        return ""
    return ""


def _search_korean_via_langlink(
    query: str,
    *,
    limit: int,
    timeoutSeconds: float,
) -> list[WikipediaSearchResult]:
    """Korean query -> ko.wikipedia title search -> EN langlink -> EN summary.

    en.wikipedia title search cannot resolve Korean text (always no_result),
    so the deterministic KO->EN anchor goes through the Korean article's
    inter-language link (떡볶이 -> Tteokbokki), verified against live data.
    """
    url = KO_WIKIPEDIA_SEARCH_ENDPOINT + "?" + urllib.parse.urlencode({
        "q": query, "limit": max(1, min(limit, 5)),
    })
    request = urllib.request.Request(url, headers=WIKI_REQUEST_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeoutSeconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return []

    queryTokens = [token for token in query.split() if len(token) >= 2] or [query]
    rows: list[WikipediaSearchResult] = []
    for rawItem in _ReadSearchItems(payload):
        koTitle = _StripMarkup(str(rawItem.get("title") or "")).strip()
        if not koTitle:
            continue
        # Relevance guard: ko title search prefix-matches unrelated articles
        # ("군만두" -> "군발두통"). Bidirectional containment keeps redirects
        # to the base dish ("군만두" -> "만두") while dropping strangers.
        compactTitle = re.sub(r"\s+|\([^)]*\)", "", koTitle)
        if not any(
            token in compactTitle or (len(compactTitle) >= 2 and compactTitle in token)
            for token in queryTokens
        ):
            continue
        enTitle = _fetch_en_langlink(koTitle, timeoutSeconds=timeoutSeconds)
        if not enTitle:
            continue
        summary = _fetch_summary_snippet(enTitle, timeoutSeconds=timeoutSeconds)
        rows.append(
            WikipediaSearchResult(
                title=enTitle,
                description=f"ko:{koTitle}",
                snippet=summary or enTitle,
                link=f"https://en.wikipedia.org/wiki/{urllib.parse.quote(enTitle.replace(' ', '_'))}",
            ),
        )
        if len(rows) >= limit:
            break
    return rows


def _search_wikipedia(
    query: str,
    *,
    limit: int,
    timeoutSeconds: float,
) -> list[WikipediaSearchResult]:
    # Korean queries never match en.wikipedia title search; route them through
    # the ko-article -> EN langlink bridge first.
    if _KOREAN_RE.search(query):
        rows = _search_korean_via_langlink(query, limit=limit, timeoutSeconds=timeoutSeconds)
        if rows:
            return rows
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


def _BuildSearchUrl(query: str, *, limit: int) -> str:
    return WIKIPEDIA_SEARCH_ENDPOINT + "?" + urllib.parse.urlencode(
        {
            "q": query,
            "limit": max(1, min(limit, 10)),
            "format": "json",
        },
    )


def _StripMarkup(markup: str) -> str:
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub("", markup))).strip()


def _HashEntry(title: str, description: str, snippet: str, link: str) -> str:
    raw = "\n".join([title, description, snippet, link])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
