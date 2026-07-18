"""Wikipedia encyclopedia evidence lookup."""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from bussiness_logic.product.model.product_understanding import (
    EncyclopediaEntryDto,
    EncyclopediaEvidenceSet,
)


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
# [8회차-1 (가) 철거] FOOD_RELATED_HINT_RE(식품 화이트리스트)·OFFTOPIC_RE
# (주제 블랙리스트) 전량 철거 — 정답 문서 기각 실측(Mechanical pencil
# food_signal_mismatch, Diaper 본문 'person' offtopic) 근거. 기각의 폐지:
# 문서는 버리지 않고 아래 등급 승선제(GradeWikipediaRow)가 등급만 부여한다.
# 도메인 어휘 수기 재유입 금지 — 규칙 대장(handoff/RULE_LEDGER.md) 대조 감사.


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
    legalVocab: frozenset[str] = frozenset(),
    dictTitles: frozenset[str] = frozenset(),
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

    graded: list[tuple[WikipediaSearchResult, str, str]] = []
    searchError = ""
    # [8회차-1] 등급 승선제 — 기각 없음. 후보열 순회: 강/중 문서가 나오는
    # 첫 후보에서 확정, 없으면 첫 유효 후보의 약 등급 기록 보존.
    weakFallback: list[tuple[WikipediaSearchResult, str, str]] = []
    weakQuery = ""
    for candidate in _QueryCandidates(normalizedQuery):
        try:
            rows, _st, _rs = _lookup_candidate(
                candidate,
                limit=display,
                timeoutSeconds=timeoutSeconds,
            )
        except Exception as exc:  # noqa: BLE001 — keep lookup tolerant
            searchError = f"{type(exc).__name__}: {exc}"
            continue
        if not rows:
            continue
        searchError = ""
        rowsGraded = [
            (row, *GradeWikipediaRow(
                candidate, row,
                legalVocab=legalVocab, dictTitles=dictTitles))
            for row in rows
        ]
        if any(g in ("strong", "medium") for _r, g, _e in rowsGraded):
            graded = rowsGraded
            normalizedQuery = candidate
            break
        if not weakFallback:
            weakFallback = rowsGraded
            weakQuery = candidate

    if not graded and weakFallback:
        graded = weakFallback
        normalizedQuery = weakQuery
    if not graded:
        return EncyclopediaEvidenceSet(
            encyclopediaEvidenceId=encyclopediaEvidenceId,
            productId=productId,
            query=normalizedQuery,
            configured=True,
            qualityStatus="error" if searchError else "no_result",
            qualityReasons=("lookup_error",) if searchError else ("no_items",),
            error=searchError,
        )

    counts = {"strong": 0, "medium": 0, "weak": 0}
    for _r, g, _e in graded:
        counts[g] = counts.get(g, 0) + 1
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
                grade=grade,
                gradeEvidence=evidence,
            )
            for row, grade, evidence in graded
        ),
        qualityStatus="graded_entries",
        qualityReasons=(
            "grade_boarding_v1",
            f"strong={counts['strong']},medium={counts['medium']},weak={counts['weak']}",
        ),
    )


def GradeWikipediaRow(
    query: str,
    row: WikipediaSearchResult,
    *,
    legalVocab: frozenset[str] = frozenset(),
    dictTitles: frozenset[str] = frozenset(),
) -> tuple[str, str]:
    """[8회차-1] 등급 승선제 — 기각의 폐지. 전부 결정론, 수기 어휘 0.

    강(strong): ko 표제가 쿼리 정규화 일치 또는 관세청 사전 표제 대응 →
      전문 승선. 중(medium): 문서 en 토큰 ∩ 법정 서술 어휘(legalVocab —
      cn_chapter_index 기계 도출, 수기 금지) ≥ 2 → 성립 대목만 승선.
    약(weak): 무근거 → identity 입력 불승선, 근거 기록만 (전주 칼국수
      도시 문서 하이재킹의 방어를 가드 대신 이 불승선이 승계한다).
    등급의 소비는 identity 프롬프트 조립·근거 표시 2곳 한정 — 결정층
    자격은 D3 단독 소유(이중 판정 금지).
    """
    queryText = str(query or "").strip()
    if not queryText:
        return "weak", "empty_query"
    # ko 표제 = _search_korean_wikipedia_as_english가 description 선두에
    # 실은 koreanTitle (row 구성 계약, :318-329)
    koTitle = str(row.description or "").split(" ")[0].strip()
    normQ = re.sub(r"\s+", "", queryText)
    normT = re.sub(r"\s+", "", koTitle)
    if normT and (normT == normQ or normT in dictTitles):
        return "strong", f"title_match:{koTitle}"
    enToks = _Tokenize(f"{row.title} {row.snippet}") - {
        t for t in _Tokenize(f"{row.title} {row.snippet}") if HANGUL_RE.search(t)}
    hits = sorted(enToks & legalVocab)
    # 중의 연결 전제: ko 표제·쿼리의 2자+ 연속 한글 공유(문자열 연산 —
    # 수기 어휘 0). 법정 어휘만으로는 '무관 문서가 자기 도메인 어휘로
    # 승선'하는 남발이 실측됨(수제비→Homemade firearm '사제 총기').
    # 샤프심↔'샤프 펜슬'(샤프)·기저귀↔'기저귀'는 통과, 수제비↔'수비수'는
    # 공유 2자 부재로 차단.
    if len(hits) >= 2 and _KoLinked(queryText, koTitle):
        return "medium", "legal_vocab:" + ",".join(hits[:6])
    # 전 매치 한국어 표제 겹침(구 가드의 query_overlap)은 강·중 근거가
    # 아니면 등급을 만들지 않는다 — 관계어('이상') 겹침 통과 사고의 처방.
    return "weak", ("legal_vocab_hits:" + ",".join(hits[:2])) if hits else "no_ground"


def _KoLinked(query: str, koTitle: str) -> bool:
    """2자 이상 연속 한글 공유 — 문서·상품 연결의 최소 전제 (문자열 연산)."""
    q = re.sub(r"[^가-힣]", "", str(query or ""))
    ti = re.sub(r"[^가-힣]", "", str(koTitle or ""))
    if len(q) < 2 or len(ti) < 2:
        return not q or not ti  # 한글 부재(영문 쿼리 등)면 전제 면제
    return any(q[i:i + 2] in ti for i in range(len(q) - 1))


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
    # (나) 문법·연산어 — 단위·치수·관계어(수량 문법 lane, 규칙 대장 등재).
    # 치수(mm/cm)는 쿼리 노이즈로만 스트립하되 fact 자체는 DTO 치수 슬롯
    # 소관(G-7). 관계어(이상/이하/미만/초과)는 표제 승격 사고의 원인
    # (샤프심→'이상 샤프심'→이상심리학 실측)이라 쿼리에서 제거.
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:g|kg|ml|l|mm|cm|개입|팩|종|인분)\b", " ", text, flags=re.I)
    text = re.sub(r"(?:^|\s)(?:이상|이하|미만|초과|택\s*1|택1)(?=\s|$)", " ", text)
    # [메인 병합 보존] 수량 표기 제거 후 남는 홑 기호·1자 라틴('X','×') —
    # 검색 잡음. 한글 1자는 보존(밤·김).
    text = re.sub(r"(?<!\S)[A-Za-z×*+&/-](?!\S)", " ", text)
    # [8회차-1 (가) 철거] 한글 마케팅어 목록(냉동·냉장·상온·간편·프리미엄)
    # 삭제 — 도메인 편향 어휘. 상태어는 지각 fact lane 소관.
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
    koFallbackRows: list[WikipediaSearchResult] = []
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
        if not englishTitle:
            # [메인 병합 보존] en 인터위키 부재 = 폐기가 아니라 ko 원문 승선
            # (백설기 실측). 승선 자격은 아래 등급제(GradeWikipediaRow)가
            # ko 표제 일치/법정 어휘 교차로 판정 — 여기서 버리면 등급제가
            # 볼 기회 자체가 없다.
            koFallbackRows.append(
                WikipediaSearchResult(
                    title=koreanTitle,
                    description=koreanDescription,
                    snippet=koreanDescription or koreanTitle,
                    link="https://ko.wikipedia.org/wiki/"
                    + urllib.parse.quote(koreanTitle.replace(" ", "_")),
                ),
            )
            continue
        if englishTitle in seenTitles:
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
    return rows or koFallbackRows[:limit]


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
