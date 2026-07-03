"""Pipeline DTOs for product understanding and HS2 routing."""

from __future__ import annotations

from dataclasses import dataclass, field


JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _desc(text: str) -> dict[str, str]:
    return {"description": text}


@dataclass(frozen=True, slots=True)
class CoiEvidenceSet:
    coiEvidenceId: str = field(metadata=_desc("COI 근거 묶음 ID"))
    productId: str = field(metadata=_desc("대상 상품 ID"))
    matchedDocuments: tuple[str, ...] = field(default=(), metadata=_desc("매칭된 문서 경로"))
    matchedTexts: tuple[str, ...] = field(default=(), metadata=_desc("매칭된 문서 본문"))
    matchScores: tuple[int, ...] = field(default=(), metadata=_desc("문서 매칭 점수"))
    error: str = field(default="", metadata=_desc("COI 로딩 오류"))

    def ToBlackboard(self, *, createdBy: str, createdAt: str) -> dict[str, JsonValue]:
        return {
            "object_type": "CoiEvidenceSet",
            "created_by": createdBy,
            "created_at": createdAt,
            "coi_evidence_id": self.coiEvidenceId,
            "product_id": self.productId,
            "matched_documents": list(self.matchedDocuments),
            "matched_texts": list(self.matchedTexts),
            "match_scores": list(self.matchScores),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class EncyclopediaEntryDto:
    title: str = field(metadata=_desc("백과사전 문서 제목"))
    description: str = field(metadata=_desc("백과사전 요약 설명"))
    link: str = field(metadata=_desc("백과사전 원문 링크"))
    contentHash: str = field(metadata=_desc("중복 제거용 콘텐츠 해시"))

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "title": self.title,
            "description": self.description,
            "link": self.link,
            "content_hash": self.contentHash,
        }


@dataclass(frozen=True, slots=True)
class EncyclopediaEvidenceSet:
    encyclopediaEvidenceId: str = field(metadata=_desc("백과사전 근거 묶음 ID"))
    productId: str = field(metadata=_desc("대상 상품 ID"))
    query: str = field(metadata=_desc("백과사전 조회 질의"))
    configured: bool = field(metadata=_desc("조회 설정 활성 여부"))
    entries: tuple[EncyclopediaEntryDto, ...] = field(default=(), metadata=_desc("조회된 백과사전 항목"))
    qualityStatus: str = field(default="unconfigured", metadata=_desc("조회 품질 상태"))
    qualityReasons: tuple[str, ...] = field(default=(), metadata=_desc("조회 품질 판단 이유"))
    error: str = field(default="", metadata=_desc("백과사전 조회 오류"))

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "encyclopedia_evidence_id": self.encyclopediaEvidenceId,
            "product_id": self.productId,
            "query": self.query,
            "configured": self.configured,
            "entries": [entry.ToTrace() for entry in self.entries],
            "quality_status": self.qualityStatus,
            "quality_reasons": list(self.qualityReasons),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class DistilledIdentityFacts:
    distilledIdentityId: str = field(metadata=_desc("Wikipedia 기반 identity seed ID"))
    productId: str = field(metadata=_desc("대상 상품 ID"))
    sourceEncyclopediaEvidenceId: str = field(metadata=_desc("원천 백과사전 근거 묶음 ID"))
    commercialIdentity: str = field(default="", metadata=_desc("백과사전 기반 상품 정체성"))
    normalizedDescription: str = field(default="", metadata=_desc("백과사전 기반 정규 설명"))
    identityTerms: tuple[str, ...] = field(default=(), metadata=_desc("백과사전 기반 정체성 토큰"))
    productFormSignalTerms: tuple[str, ...] = field(default=(), metadata=_desc("백과사전 원문 상품 형태 신호"))
    processingSignalTerms: tuple[str, ...] = field(default=(), metadata=_desc("백과사전 원문 가공 상태 신호"))
    sourceTitles: tuple[str, ...] = field(default=(), metadata=_desc("사용한 백과사전 제목"))
    sourceDescriptions: tuple[str, ...] = field(default=(), metadata=_desc("사용한 백과사전 설명"))
    sourceLinks: tuple[str, ...] = field(default=(), metadata=_desc("사용한 백과사전 링크"))
    qualityStatus: str = field(default="", metadata=_desc("백과사전 조회 품질 상태"))

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "distilled_identity_id": self.distilledIdentityId,
            "product_id": self.productId,
            "source_encyclopedia_evidence_id": self.sourceEncyclopediaEvidenceId,
            "commercial_identity": self.commercialIdentity,
            "normalized_description": self.normalizedDescription,
            "identity_terms": list(self.identityTerms),
            "product_form_signal_terms": list(self.productFormSignalTerms),
            "processing_signal_terms": list(self.processingSignalTerms),
            "source_titles": list(self.sourceTitles),
            "source_descriptions": list(self.sourceDescriptions),
            "source_links": list(self.sourceLinks),
            "quality_status": self.qualityStatus,
        }


@dataclass(frozen=True, slots=True)
class IdentityHintSet:
    identityHintId: str = field(metadata=_desc("Identity 힌트 묶음 ID"))
    productId: str = field(metadata=_desc("대상 상품 ID"))
    commercialIdentity: str = field(default="", metadata=_desc("상업적 상품 정체성"))
    ingredientClass: str = field(default="other", metadata=_desc("주요 원재료 계열"))
    foodForm: str = field(default="other", metadata=_desc("상품 형태 힌트"))
    processingState: str = field(default="unknown", metadata=_desc("가공 상태 힌트"))
    normalizedTariffDescription: str = field(default="", metadata=_desc("관세 분류용 정규 설명"))
    identityTerms: tuple[str, ...] = field(default=(), metadata=_desc("상품 정체성 토큰"))
    compositionTerms: tuple[str, ...] = field(default=(), metadata=_desc("구성 성분 토큰"))
    processingTerms: tuple[str, ...] = field(default=(), metadata=_desc("가공 관련 토큰"))
    confidence: float = field(default=0.0, metadata=_desc("힌트 신뢰도"))
    conflictReason: str = field(default="", metadata=_desc("힌트 충돌 이유"))
    translatedProductName: str = field(default="", metadata=_desc("영문 번역 상품명"))
    productFormTerms: tuple[str, ...] = field(default=(), metadata=_desc("상품 형태 후보 토큰"))
    domainHints: tuple[str, ...] = field(default=(), metadata=_desc("도메인 라우팅 힌트"))
    chapterHintTerms: tuple[str, ...] = field(default=(), metadata=_desc("HS2 라우팅 키워드 힌트"))
    chapterHintSourceTerms: tuple[str, ...] = field(default=(), metadata=_desc("HS2 힌트 생성 근거 토큰"))
    chapterHintBasis: str = field(default="", metadata=_desc("HS2 힌트 생성 근거 설명"))
    chapterHintStatus: str = field(default="", metadata=_desc("HS2 힌트 상태"))
    understandingMode: str = field(default="regex", metadata=_desc("힌트 생성 방식"))
    needsReview: bool = field(default=False, metadata=_desc("수동 검토 필요 여부"))
    llmError: str = field(default="", metadata=_desc("LLM 힌트 생성 오류"))

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "identity_hint_id": self.identityHintId,
            "product_id": self.productId,
            "commercial_identity": self.commercialIdentity,
            "ingredient_class": self.ingredientClass,
            "food_form": self.foodForm,
            "processing_state": self.processingState,
            "normalized_tariff_description": self.normalizedTariffDescription,
            "identity_terms": list(self.identityTerms),
            "composition_terms": list(self.compositionTerms),
            "processing_terms": list(self.processingTerms),
            "confidence": self.confidence,
            "conflict_reason": self.conflictReason,
            "translated_product_name": self.translatedProductName,
            "product_form_terms": list(self.productFormTerms),
            "domain_hints": list(self.domainHints),
            "chapter_hint_terms": list(self.chapterHintTerms),
            "chapter_hint_source_terms": list(self.chapterHintSourceTerms),
            "chapter_hint_basis": self.chapterHintBasis,
            "chapter_hint_status": self.chapterHintStatus,
            "understanding_mode": self.understandingMode,
            "needs_review": self.needsReview,
            "llm_error": self.llmError,
        }


@dataclass(frozen=True, slots=True)
class CompositionFactSet:
    processingState: str = field(default="unknown", metadata=_desc("가공 상태"))
    principalIngredient: str = field(default="", metadata=_desc("주성분 후보"))
    ingredientClasses: tuple[str, ...] = field(default=(), metadata=_desc("성분 계열 목록"))
    ingredientPercentages: tuple[dict[str, JsonValue], ...] = field(default=(), metadata=_desc("성분 함량 정보"))
    compositionTerms: tuple[str, ...] = field(default=(), metadata=_desc("성분/함량 분류 토큰"))
    processingTerms: tuple[str, ...] = field(default=(), metadata=_desc("가공 조건 토큰"))
    compositionBasis: str = field(default="label", metadata=_desc("성분 정보 출처"))
    containsWrapperOrDough: bool = field(default=False, metadata=_desc("피/도우 포함 여부"))
    containsSauceOrBroth: bool = field(default=False, metadata=_desc("소스/육수 포함 여부"))
    allergenTermsExcluded: tuple[str, ...] = field(default=(), metadata=_desc("분류에서 제외한 알레르겐 문구"))
    missingCompositionFacts: tuple[str, ...] = field(default=(), metadata=_desc("부족한 성분 정보"))

    def ToTrace(self) -> dict[str, JsonValue]:
        return {
            "processing_state": self.processingState,
            "principal_ingredient": self.principalIngredient,
            "ingredient_classes": list(self.ingredientClasses),
            "ingredient_percentages": list(self.ingredientPercentages),
            "composition_terms": list(self.compositionTerms),
            "processing_terms": list(self.processingTerms),
            "composition_basis": self.compositionBasis,
            "contains_wrapper_or_dough": self.containsWrapperOrDough,
            "contains_sauce_or_broth": self.containsSauceOrBroth,
            "allergen_terms_excluded": list(self.allergenTermsExcluded),
            "missing_composition_facts": list(self.missingCompositionFacts),
        }


@dataclass(frozen=True, slots=True)
class ProductUnderstandingPackage:
    understandingId: str = field(metadata=_desc("상품 이해 패키지 ID"))
    productId: str = field(metadata=_desc("대상 상품 ID"))
    sourceProductId: str = field(metadata=_desc("원천 InputEvidenceState ID"))
    productName: str = field(metadata=_desc("상품명"))
    shortDescription: str = field(metadata=_desc("짧은 상품 설명"))
    classificationText: str = field(metadata=_desc("분류 입력용 통합 텍스트"))
    reconstructedFactTexts: tuple[str, ...] = field(metadata=_desc("LLM Reconstruction 정규화 텍스트"))
    reconstructedProductFacts: tuple[dict[str, JsonValue], ...] = field(metadata=_desc("LLM Reconstruction 구조화 fact"))
    distilledIdentity: DistilledIdentityFacts = field(metadata=_desc("Wikipedia 기반 identity seed"))
    identityHints: IdentityHintSet = field(metadata=_desc("HS2-HS4용 identity 힌트"))
    compositionFacts: CompositionFactSet = field(metadata=_desc("HS6-CN8용 성분/함량 fact"))
    coiEvidence: CoiEvidenceSet = field(metadata=_desc("COI 보조 근거"))
    encyclopediaEvidence: EncyclopediaEvidenceSet = field(metadata=_desc("백과사전 보조 근거"))
    routingTerms: tuple[str, ...] = field(metadata=_desc("HS2 라우팅 입력 토큰"))
    blockedRoutingTerms: tuple[str, ...] = field(default=(), metadata=_desc("라우팅 제외 토큰"))
    excludedFromRoutingTerms: tuple[str, ...] = field(default=(), metadata=_desc("라우팅 입력에서 제외된 토큰"))
    unknowns: tuple[str, ...] = field(default=(), metadata=_desc("부족한 입력 정보"))

    def ToBlackboard(self, *, createdBy: str, createdAt: str) -> dict[str, JsonValue]:
        return {
            "object_type": "ProductUnderstandingPackage",
            "created_by": createdBy,
            "created_at": createdAt,
            "understanding_id": self.understandingId,
            "product_id": self.productId,
            "source_product_id": self.sourceProductId,
            "product_name": self.productName,
            "short_description": self.shortDescription,
            "classification_text": self.classificationText,
            "reconstructed_fact_texts": list(self.reconstructedFactTexts),
            "reconstructed_product_facts": list(self.reconstructedProductFacts),
            "distilled_identity": self.distilledIdentity.ToTrace(),
            "identity_hints": self.identityHints.ToTrace(),
            "composition_facts": self.compositionFacts.ToTrace(),
            "coi_evidence": self.coiEvidence.ToBlackboard(
                createdBy=createdBy,
                createdAt=createdAt,
            ),
            "encyclopedia_evidence": self.encyclopediaEvidence.ToTrace(),
            "routing_terms": list(self.routingTerms),
            "blocked_routing_terms": list(self.blockedRoutingTerms),
            "excluded_from_routing_terms": list(self.excludedFromRoutingTerms),
            "unknowns": list(self.unknowns),
        }


@dataclass(frozen=True, slots=True)
class Hs2RoutingDecision:
    routingDecisionId: str = field(metadata=_desc("HS2 라우팅 결정 ID"))
    productId: str = field(metadata=_desc("대상 상품 ID"))
    sourceUnderstandingId: str = field(metadata=_desc("원천 ProductUnderstandingPackage ID"))
    allowedHs2: tuple[str, ...] = field(metadata=_desc("허용 HS2 후보"))
    blockedHs2: tuple[str, ...] = field(metadata=_desc("차단 HS2 후보"))
    enforceHs2Boundary: bool = field(metadata=_desc("HS2 후보 범위 강제 여부"))
    fallbackAllowed: bool = field(metadata=_desc("후보 없음/실패 시 fallback 허용 여부"))
    domainScopes: tuple[str, ...] = field(metadata=_desc("도메인 scope 힌트"))
    preGateDomains: tuple[str, ...] = field(metadata=_desc("사전 게이트 도메인"))
    routingBasis: dict[str, JsonValue] = field(metadata=_desc("라우팅 판단 근거"))
    candidateChapterDetails: tuple[dict[str, JsonValue], ...] = field(
        default=(),
        metadata=_desc("HS2 후보별 점수와 매칭 근거"),
    )
    missingFacts: tuple[str, ...] = field(default=(), metadata=_desc("라우팅에 부족한 fact"))

    def ToBlackboard(self, *, createdBy: str, createdAt: str) -> dict[str, JsonValue]:
        return {
            "object_type": "Hs2RoutingDecision",
            "created_by": createdBy,
            "created_at": createdAt,
            "routing_decision_id": self.routingDecisionId,
            "product_id": self.productId,
            "source_understanding_id": self.sourceUnderstandingId,
            "allowed_hs2": list(self.allowedHs2),
            "blocked_hs2": list(self.blockedHs2),
            "enforce_hs2_boundary": self.enforceHs2Boundary,
            "fallback_allowed": self.fallbackAllowed,
            "domain_scopes": list(self.domainScopes),
            "pre_gate_domains": list(self.preGateDomains),
            "routing_basis": dict(self.routingBasis),
            "candidate_chapter_details": list(self.candidateChapterDetails),
            "missing_facts": list(self.missingFacts),
        }
