"""Naver encyclopedia evidence lookup."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from agents.pipeline_dto import EncyclopediaEntryDto, EncyclopediaEvidenceSet


NAVER_ENCYC_ENDPOINT = "https://openapi.naver.com/v1/search/encyc.json"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NaverCredentials:
    clientId: str
    clientSecret: str


def ReadNaverCredentials() -> NaverCredentials | None:
    clientId = (os.environ.get("NAVER_CLIENT_ID") or "").strip()
    clientSecret = (os.environ.get("NAVER_CLIENT_SECRET") or "").strip()
    if not clientId or not clientSecret:
        return None
    return NaverCredentials(clientId=clientId, clientSecret=clientSecret)


def LookupEncyclopediaEvidence(
    *,
    encyclopediaEvidenceId: str,
    productId: str,
    query: str,
    display: int = 3,
    timeoutSeconds: float = 10.0,
) -> EncyclopediaEvidenceSet:
    normalizedQuery = query.strip()
    credentials = ReadNaverCredentials()
    if not normalizedQuery:
        return EncyclopediaEvidenceSet(
            encyclopediaEvidenceId=encyclopediaEvidenceId,
            productId=productId,
            query=normalizedQuery,
            configured=credentials is not None,
            qualityStatus="no_query",
            qualityReasons=("empty_query",),
        )
    if credentials is None:
        return EncyclopediaEvidenceSet(
            encyclopediaEvidenceId=encyclopediaEvidenceId,
            productId=productId,
            query=normalizedQuery,
            configured=False,
            qualityStatus="unconfigured",
            qualityReasons=("naver_credentials_missing",),
            error="NAVER_CLIENT_ID/NAVER_CLIENT_SECRET not set",
        )

    url = NAVER_ENCYC_ENDPOINT + "?" + urllib.parse.urlencode(
        {"query": normalizedQuery, "display": max(1, min(display, 10))},
    )
    request = urllib.request.Request(
        url,
        headers={
            "X-Naver-Client-Id": credentials.clientId,
            "X-Naver-Client-Secret": credentials.clientSecret,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeoutSeconds) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return EncyclopediaEvidenceSet(
            encyclopediaEvidenceId=encyclopediaEvidenceId,
            productId=productId,
            query=normalizedQuery,
            configured=True,
            qualityStatus="error",
            qualityReasons=("lookup_error",),
            error=f"{type(exc).__name__}: {exc}",
        )

    items = decoded.get("items") if isinstance(decoded, dict) else []
    entries: list[EncyclopediaEntryDto] = []
    if isinstance(items, list):
        for item in items[:display]:
            if not isinstance(item, dict):
                continue
            title = _StripMarkup(str(item.get("title") or ""))
            description = _StripMarkup(str(item.get("description") or ""))
            link = str(item.get("link") or "")
            if not title and not description:
                continue
            entries.append(
                EncyclopediaEntryDto(
                    title=title,
                    description=description,
                    link=link,
                    contentHash=_HashEntry(title, description, link),
                ),
            )

    return EncyclopediaEvidenceSet(
        encyclopediaEvidenceId=encyclopediaEvidenceId,
        productId=productId,
        query=normalizedQuery,
        configured=True,
        entries=tuple(entries),
        qualityStatus="raw_entries" if entries else "no_result",
        qualityReasons=("raw_not_routing_input",) if entries else ("no_items",),
    )


def _StripMarkup(markup: str) -> str:
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub("", markup))).strip()


def _HashEntry(title: str, description: str, link: str) -> str:
    raw = "\n".join([title, description, link])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
