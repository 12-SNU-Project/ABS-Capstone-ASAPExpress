"""Distill compact commodity identity from encyclopedia evidence."""

from __future__ import annotations

import re

from bussiness_logic.product.model.product_understanding import (
    DistilledIdentityFacts,
    EncyclopediaEvidenceSet,
)


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _BoardedSentences(entry) -> str:
    """중 등급의 '성립 대목' — 등급 근거 토큰(legal_vocab:…)이 실린 문장만."""
    evidence = str(getattr(entry, "gradeEvidence", "") or "")
    toks = set()
    if ":" in evidence:
        toks = {w for w in evidence.split(":", 1)[1].split(",") if w}
    if not toks:
        return str(entry.description or "")
    kept = [
        s for s in _SENT_SPLIT.split(str(entry.description or ""))
        if any(w in s.lower() for w in toks)
    ]
    return " ".join(kept) if kept else str(entry.description or "")
PRODUCT_FORM_SIGNAL_PATTERN = re.compile(
    r"noodle|pasta|bread|pastry|cake|sauce|soup|broth|stew|condiment|beverage|cosmetic|cream|lotion|shampoo|면|국수|빵|소스|국|탕|찌개|음료|화장품|크림|로션|샴푸",
    re.I,
)
PROCESSING_SIGNAL_PATTERN = re.compile(
    r"prepared|processed|cooked|fried|roasted|seasoned|marinated|preserved|dried|smoked|frozen|chilled|가공|조리|볶음|구이|양념|냉동|건조|훈제",
    re.I,
)


class IdentityDistillerService:
    def BuildFacts(
        self,
        *,
        distilledIdentityId: str,
        productId: str,
        encyclopediaEvidence: EncyclopediaEvidenceSet,
    ) -> DistilledIdentityFacts:
        # [8회차-1] 등급 승선제 소비 ①: 강=전문, 중=성립 대목(등급 근거
        # 토큰이 실린 문장)만, 약=identity 불승선(근거는 source_*에 기록).
        # 컷 수리(다): 16→64 / 12→24 토큰 — 볼펜 조성 문장(steel/brass/
        # tungsten carbide, 17토큰 이후) 전량 유실 실측의 처방.
        text = self._EvidenceText(encyclopediaEvidence)
        identityTerms = self._Terms(text, limit=64)
        return DistilledIdentityFacts(
            distilledIdentityId=distilledIdentityId,
            productId=productId,
            sourceEncyclopediaEvidenceId=encyclopediaEvidence.encyclopediaEvidenceId,
            commercialIdentity=self._CommercialIdentity(encyclopediaEvidence),
            normalizedDescription=" ".join(identityTerms[:24]),
            identityTerms=identityTerms,
            productFormSignalTerms=self._SignalTerms(text, PRODUCT_FORM_SIGNAL_PATTERN),
            processingSignalTerms=self._SignalTerms(text, PROCESSING_SIGNAL_PATTERN),
            sourceTitles=tuple(entry.title for entry in encyclopediaEvidence.entries),
            sourceDescriptions=tuple(entry.description for entry in encyclopediaEvidence.entries),
            sourceLinks=tuple(entry.link for entry in encyclopediaEvidence.entries),
            qualityStatus=encyclopediaEvidence.qualityStatus,
        )

    @staticmethod
    def _EvidenceText(encyclopediaEvidence: EncyclopediaEvidenceSet) -> str:
        parts: list[str] = []
        # 강 우선 승선: 강 문서가 있으면 중은 identity 입력에서 제외 —
        # 강(표제 일치)의 정체를 중(도메인 직격)의 잡문서가 희석하는
        # 남발 실측(수제비 강 승선 옆에 무관 중 문서 동승)의 처방.
        _has_strong = any(
            str(getattr(e, "grade", "") or "") == "strong"
            for e in encyclopediaEvidence.entries)
        for entry in encyclopediaEvidence.entries:
            grade = str(getattr(entry, "grade", "") or "")
            if grade == "weak":
                continue  # 약 = identity 불승선 (근거 기록만)
            if grade == "medium" and _has_strong:
                continue
            if grade == "medium":
                parts.append(
                    f"{entry.title} {_BoardedSentences(entry)}")
                continue
            # strong 또는 구판 무등급(하위 호환) = 전문
            parts.append(f"{entry.title} {entry.description}")
        return "\n".join(parts)

    @staticmethod
    def _CommercialIdentity(encyclopediaEvidence: EncyclopediaEvidenceSet) -> str:
        for entry in encyclopediaEvidence.entries:
            if str(getattr(entry, "grade", "") or "") == "weak":
                continue  # 약 등급 표제는 정체가 될 수 없다 (하이재킹 방어 승계)
            if entry.title.strip():
                return entry.title.strip()
        return ""

    @staticmethod
    def _Terms(text: str, *, limit: int) -> tuple[str, ...]:
        out: list[str] = []
        for token in TOKEN_PATTERN.findall(text):
            normalized = token.strip()
            if len(normalized) < 2 or normalized in out:
                continue
            out.append(normalized)
            if len(out) >= limit:
                break
        return tuple(out)

    @staticmethod
    def _SignalTerms(text: str, pattern: re.Pattern[str], *, limit: int = 12) -> tuple[str, ...]:
        out: list[str] = []
        for match in pattern.finditer(text):
            term = match.group(0).strip()
            if term and term.lower() not in {item.lower() for item in out}:
                out.append(term)
            if len(out) >= limit:
                break
        return tuple(out)
