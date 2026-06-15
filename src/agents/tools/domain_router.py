"""
DomainRouterTool — 제품 → regulatory domain.

Owned by Document_Agent. Hybrid design:

  1) Deterministic fast-path  ← THIS STEP
     - chapter → 1-2 도메인 매핑 테이블
     - 명백한 키워드 (예: "lipstick" → cosmetics)
     - 단일 도메인 결과면 그대로 반환

  2) LLM fallback (낙지볶음 같은 ambiguous case)
     - 추후 step 에서 wire (bridge.RuntimeAdapter 재사용)
     - 현재는 ambiguous 표시만 반환 → Document_Agent 가 backtracking_signal 발행

도메인 vocabulary (asap_evidence.yaml 의 RegulatoryDomain enum 과 일치):
  food / cosmetics / animal_origin / cites / hazardous /
  pharmaceutical / sanctions / dual_use / other
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Fast-path table — chapter → primary regulatory domains.
# 한 chapter 에 여러 domain 매핑 가능 (예: 02류 = food + animal_origin).
# 출처: Domain_Scope_Routes spec (v2 core) + EU 일반 규제 매트릭스.
# ---------------------------------------------------------------------------
_CHAPTER_TO_DOMAINS: dict[str, list[str]] = {
    # Live animals + animal products (SPS, CHED-P 영역)
    "01": ["animal_origin"],                       # live animals
    "02": ["food", "animal_origin"],               # meat
    "03": ["food", "animal_origin"],               # fish/seafood
    "04": ["food", "animal_origin"],               # dairy/eggs/honey
    "05": ["animal_origin"],                       # products of animal origin n.e.s.
    # Plant products (SPS 식물 검역)
    "06": ["food"],                                # live plants/flowers (선택적 SPS)
    "07": ["food"],                                # vegetables
    "08": ["food"],                                # fruits
    "09": ["food"],                                # coffee/tea/spices
    "10": ["food"],                                # cereals
    "11": ["food"],                                # flour/starch
    "12": ["food"],                                # oilseeds
    "13": ["food"],                                # vegetable saps/extracts
    "14": ["food"],                                # vegetable plaiting materials
    "15": ["food"],                                # animal/vegetable fats and oils
    # Prepared food (가공식품 — Phase 1 핵심)
    "16": ["food", "animal_origin"],               # meat/fish preparations
    "17": ["food"],                                # sugars/sugar confectionery
    "18": ["food"],                                # cocoa/chocolate
    "19": ["food"],                                # cereal preparations (라면 등)
    "20": ["food"],                                # preparations of vegetables/fruits
    "21": ["food"],                                # misc edible preparations (소스 등)
    "22": ["food"],                                # beverages
    "23": ["food", "animal_origin"],               # animal feed
    "24": ["food"],                                # tobacco
    # Mineral / chemical (REACH/CMR 영역)
    "25": ["hazardous"],                           # salt/cement/sulphur
    "26": ["hazardous"],                           # ores
    "27": ["hazardous"],                           # mineral fuels
    "28": ["hazardous"],                           # inorganic chemicals
    "29": ["hazardous", "pharmaceutical"],         # organic chemicals (의약품 원료 포함)
    "30": ["pharmaceutical"],                      # pharmaceutical products
    "31": ["hazardous"],                           # fertilizers
    "32": ["hazardous", "cosmetics"],              # tanning/dyeing extracts
    "33": ["cosmetics"],                           # essential oils/cosmetics
    "34": ["cosmetics", "hazardous"],              # soap/wax (계면활성제)
    "35": ["hazardous"],                           # albuminoidal substances
    "36": ["hazardous"],                           # explosives/pyrotechnics
    "37": ["hazardous"],                           # photographic chemicals
    "38": ["hazardous"],                           # misc chemicals
    # Plastics/rubber/leather/wood — 일반 (보통 도메인 없음)
    # Textiles/footwear — 일반 (CMR substance 시 hazardous)
    # Metals/machinery/vehicles — 대부분 dual_use 후보
    "84": ["dual_use"],                            # nuclear reactors/machinery (선택적)
    "85": ["dual_use"],                            # electrical machinery
    "87": ["dual_use"],                            # vehicles (군용 후보)
    "93": ["dual_use", "sanctions"],               # arms/ammunition
}


# CITES 후보 chapter (특정 동식물 protected) — 추가 트리거
_CITES_CHAPTER_HINTS: set[str] = {"01", "02", "03", "05", "06", "12", "13", "33"}


# 명백한 키워드 → 도메인 (product_name 에 등장 시)
_KEYWORD_TO_DOMAIN: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"\b(lipstick|mascara|foundation|perfume|cologne|cream|lotion|cosmetic|shampoo|skincare|toner|essence)\b", re.I),
     ["cosmetics"]),
    (re.compile(r"\b(립스틱|마스카라|파운데이션|향수|크림|로션|화장품|샴푸|스킨|토너|에센스)\b"),
     ["cosmetics"]),
    (re.compile(r"\b(pharmaceutical|medicine|drug|tablet|capsule|antibiotic|vaccine)\b", re.I),
     ["pharmaceutical"]),
    (re.compile(r"\b(의약품|약품|항생제|백신|치료제)\b"),
     ["pharmaceutical"]),
    (re.compile(r"\b(weapon|firearm|ammunition|missile|explosive)\b", re.I),
     ["sanctions", "dual_use"]),
]


@dataclass
class DomainRouteResult:
    """One product → one or more applicable regulatory domains."""
    domains: list[str] = field(default_factory=list)            # ["food", "animal_origin"]
    confidence: float = 0.0
    decided_by: str = ""                                        # "fast_path_chapter" | "fast_path_keyword" | "ambiguous" | "llm"
    reason: str = ""
    missing_facts: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    is_ambiguous: bool = False                                  # True → caller 가 LLM fallback 호출

    def to_dict(self) -> dict:
        return {
            "domains": list(self.domains),
            "confidence": self.confidence,
            "decided_by": self.decided_by,
            "reason": self.reason,
            "missing_facts": list(self.missing_facts),
            "evidence": list(self.evidence),
            "is_ambiguous": self.is_ambiguous,
        }


class DomainRouterTool:
    """fast-path + (planned) LLM hybrid. Currently fast-path only.

    Usage:
        tool = DomainRouterTool()
        result = tool.route(
            cn8="19023010",
            product_facts={"product_name": "Korean instant ramen noodle"},
            measure_type_hints=["Veterinary control"],
        )
    """

    def __init__(self, llm_adapter=None) -> None:
        self._llm_adapter = llm_adapter

    def route(
        self,
        *,
        cn8: str,
        product_facts: dict,
        measure_type_hints: list[str] | None = None,
    ) -> DomainRouteResult:
        cn8 = (cn8 or "").strip()
        chapter = cn8[:2] if len(cn8) >= 2 else ""
        name = (product_facts.get("product_name") or "").strip()
        desc = (product_facts.get("description") or "").strip()
        haystack = f"{name} {desc}"

        evidence: list[dict] = []
        domains: list[str] = []

        # 1. Chapter fast-path
        chapter_domains = _CHAPTER_TO_DOMAINS.get(chapter, [])
        if chapter_domains:
            domains = list(chapter_domains)
            evidence.append({
                "source": "fast_path_chapter",
                "chapter": chapter,
                "domains": chapter_domains,
            })

        # 2. Keyword override / extension
        for pat, kw_domains in _KEYWORD_TO_DOMAIN:
            if pat.search(haystack):
                for d in kw_domains:
                    if d not in domains:
                        domains.append(d)
                evidence.append({
                    "source": "fast_path_keyword",
                    "pattern": pat.pattern,
                    "domains": kw_domains,
                })

        # 3. CITES trigger from measure hints (Veterinary / CITES measures already
        # show CITES in TARIC. Mirror that as a domain.)
        hints = [m.lower() for m in (measure_type_hints or [])]
        if any("cites" in h for h in hints):
            if "cites" not in domains:
                domains.append("cites")
            evidence.append({"source": "measure_hint", "hint": "CITES"})
        if any("veterinary" in h for h in hints):
            if "animal_origin" not in domains:
                domains.append("animal_origin")
            evidence.append({"source": "measure_hint", "hint": "Veterinary control"})
        if chapter in _CITES_CHAPTER_HINTS:
            # Mark CITES as a *candidate* only; do not auto-promote without a
            # measure hint or species name confirmation.
            pass

        # 4. Decision
        if not domains:
            return DomainRouteResult(
                domains=["other"],
                confidence=0.2,
                decided_by="fast_path_unmatched",
                reason=f"No fast-path rule matched chapter={chapter!r}.",
                missing_facts=["domain_unknown"],
                evidence=evidence,
                is_ambiguous=True,
            )

        # Ambiguity heuristic: >2 domains OR (food + animal_origin + product description has
        # 함량/비율 unclear) → LLM should weigh ingredient ratios.
        is_ambiguous = len(domains) >= 3 or (
            "food" in domains and "animal_origin" in domains
            and not re.search(r"\b\d{1,3}\s*%", haystack)
        )

        decided_by = "fast_path_chapter"
        confidence = 0.8 if not is_ambiguous else 0.5
        reason = (
            f"chapter {chapter} → {chapter_domains}"
            + (f"; keyword+={[p.pattern for p,_ in _KEYWORD_TO_DOMAIN if p.search(haystack)]}"
               if any(p.search(haystack) for p,_ in _KEYWORD_TO_DOMAIN) else "")
        )
        missing: list[str] = []
        if is_ambiguous:
            missing = ["primary_ingredient_ratio", "animal_origin_content_pct"]
            reason += " — multi-domain detected; recommend LLM weighting."

        return DomainRouteResult(
            domains=domains,
            confidence=confidence,
            decided_by=decided_by,
            reason=reason,
            missing_facts=missing,
            evidence=evidence,
            is_ambiguous=is_ambiguous,
        )
