"""Build ProductUnderstandingPackage from reconstructed product input."""

from __future__ import annotations

import dataclasses
import os
import re
from collections.abc import Mapping

from agents.blackboard import BlackboardStore, now_iso
from agents.component_base import BasePipelineComponent
from agents.coi_loader import LoadCoiEvidence
from agents.llm_agents import IdentityHintAgent
from agents.pipeline_dto import (
    CompositionFactSet,
    CoiEvidenceSet,
    DistilledIdentityFacts,
    EncyclopediaEvidenceSet,
    IdentityHintSet,
    JsonValue,
    ProductUnderstandingPackage,
)
from agents.tools.encyclopedia_lookup import LookupEncyclopediaEvidence
from agents.tools.identity_distiller import IdentityDistillerService


PERCENT_RE = re.compile(
    r"(?P<term>[A-Za-z가-힣][A-Za-z가-힣 /·._-]{0,39}?)"
    r"(?:\s*[\(\[（［][^)\]）］]{0,80}[\)\]）］])?"
    r"\s*(?P<percent>\d+(?:[.,]\d+)?)\s*%",
)
COMPONENT_NAME_RE = re.compile(r"[\(\[（［](?P<component>[^)\]）］]+)[)\]）］]")
CONTENT_WEIGHT_RE = re.compile(
    r"(?P<component>[A-Za-z가-힣0-9][A-Za-z가-힣0-9 /·._-]{0,40}?)"
    r"\s*(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<unit>g|kg|ml|l|개)",
    re.I,
)
COMPOSITION_PERCENT_FIELD_MARKERS = (
    "원재료",
    "원료",
    "배합",
    "성분",
    "ingredients",
    "composition",
)
WRAPPER_RE = re.compile(r"만두피|도우|반죽|wrapper|dough|pastry", re.I)
SAUCE_BROTH_RE = re.compile(r"소스|국물|육수|스프|sauce|broth|soup|stock", re.I)
ALLERGEN_RE = re.compile(
    r"알레르|알러지|알레르겐|같은\s*제조시설|동일\s*제조시설|교차|allergen|may contain|cross[- ]?contact",
    re.I,
)
# Acquisition-level noise filters (allowed hardcoding — collection, not judgement):
# origin marks ("중국산 100%") are not ingredient percentages, and admin label
# lines (packaging/expiry/shipping) are not composition terms.
ORIGIN_TERM_RE = re.compile(r"원산지|^[가-힣]{1,4}산$")
ADMIN_LABEL_LINE_RE = re.compile(
    r"^(?:포장타입|중량/?용량|판매단위|소비기한|유통기한|보관\s*방법|배송|교환|반품|고객|원산지)",
)
NUTRITION_FIELD_RE = re.compile(
    r"영양|nutrition|열량|나트륨|탄수화물|당류|지방|콜레스테롤|단백질",
    re.I,
)
COMPONENT_WEIGHT_NOISE_NAMES = frozenset({
    "내",
    "내용량",
    "총내용량",
    "열량",
    "나트륨",
    "탄수화물",
    "당류",
    "지방",
    "트랜스지방",
    "포화지방",
    "콜레스테롤",
    "단백질",
})
INGREDIENT_CLASS_RULES = (
    ("mollusc", ("낙지", "주꾸미", "문어", "오징어", "꼬막", "새꼬막", "재첩", "조개", "mollusc", "octopus", "squid", "clam", "cockle")),
    ("crustacean", ("새우", "게", "crab", "shrimp", "prawn", "lobster", "crustacean")),
    ("fish", ("어묵", "연육", "어육", "대구", "가다랑어", "참치", "fish", "cod", "surimi", "tuna")),
    ("meat", ("돼지고기", "소고기", "닭고기", "pork", "beef", "chicken", "meat")),
    ("cereal", ("밀가루", "밀", "찹쌀", "쌀", "통밀", "메밀", "떡", "면", "우동", "flour", "wheat", "rice", "cereal", "noodle")),
    ("soy_legume", ("서리태", "대두", "콩", "두부", "soy", "soybean", "bean", "tofu")),
    ("vegetable", ("고추", "대파", "양파", "무", "김치", "배추", "부추", "마늘", "나물", "vegetable", "pepper", "radish", "cabbage", "garlic")),
    ("seasoning_sauce", ("소스", "간장", "고추장", "된장", "조미", "양념", "sauce", "broth", "seasoning")),
)
INGREDIENT_TERM_ALIASES = (
    ("찹쌀", ("glutinous rice", "rice")),
    ("쌀", ("rice",)),
    ("밀가루", ("wheat flour", "flour", "wheat")),
    ("통밀", ("whole wheat", "wheat")),
    ("메밀", ("buckwheat",)),
    ("서리태", ("black soybean", "soybean", "bean")),
    ("대두", ("soybean", "soy")),
    ("재첩", ("clam", "corbicula", "mollusc")),
    ("꼬막", ("cockle", "clam", "mollusc")),
    ("새꼬막", ("cockle", "clam", "mollusc")),
    ("낙지", ("octopus", "mollusc")),
    ("주꾸미", ("webfoot octopus", "octopus", "mollusc")),
    ("오징어", ("squid", "mollusc")),
    ("새우", ("shrimp", "prawn", "crustacean")),
    ("대구", ("cod", "fish")),
    ("연육", ("surimi", "fish paste", "fish")),
    ("어육", ("fish",)),
    ("어묵", ("fish cake", "fish")),
)
PROCESSING_STATE_RULES = (
    ("frozen", ("냉동", "-18", "frozen")),
    ("cooked", ("가열하여 섭취", "유탕", "볶음", "조리", "cooked", "boiled", "fried", "roasted", "steamed")),
    ("fermented", ("발효", "김치", "fermented")),
    ("dried", ("건조", "dried")),
    ("chilled", ("냉장", "chilled")),
    ("fresh", ("신선", "fresh")),
    ("uncooked", ("비가열", "uncooked", "raw")),
    ("prepared", ("가공품", "가열하지 않고 섭취", "즉석", "소스", "양념", "prepared")),
)


class ProductUnderstandingComponent(BasePipelineComponent):
    component_name = "Product_Understanding_Component"
    stage = "Product_Understanding"
    llm_model = None

    def Run(self, store: BlackboardStore) -> None:
        bb = store.load()
        pes = bb.get("product_evidence_state") or {}
        if not isinstance(pes, dict):
            raise RuntimeError("No InputEvidenceState on the Blackboard.")
        productId = str(pes.get("product_id") or "")
        self.ReadBlackBoard(productId)

        observedFacts = pes.get("observed_facts") or {}
        if not isinstance(observedFacts, dict):
            observedFacts = {}
        productName = str(observedFacts.get("product_name") or "")
        shortDescription = str(observedFacts.get("description") or "")
        factTexts = self._ReadTextTuple(
            observedFacts.get("reconstructed_fact_texts")
            or observedFacts.get("composition")
            or [],
        )
        productFacts = self._ReadFactTuple(
            observedFacts.get("reconstructed_product_facts") or [],
        )
        inputReconstruction = observedFacts.get("input_reconstruction") or {}
        if not isinstance(inputReconstruction, dict):
            inputReconstruction = {}
        reconstructedTables = self._ReadFactTuple(
            inputReconstruction.get("reconstructed_tables") or [],
        )
        classificationText = "\n".join(
            text
            for text in (
                productName,
                shortDescription,
                *factTexts,
                *self._FactTexts(productFacts),
            )
            if text.strip()
        )

        coiEvidence = self._BuildCoiEvidenceSet(
            store,
            productId=productId,
            productName=productName,
        )
        encyclopediaEvidence = LookupEncyclopediaEvidence(
            encyclopediaEvidenceId=store.next_id("ency"),
            productId=productId,
            query=productName,
        )
        distilledIdentity = IdentityDistillerService().BuildFacts(
            distilledIdentityId=store.next_id("distid"),
            productId=productId,
            encyclopediaEvidence=encyclopediaEvidence,
        )
        identity = self._BuildIdentitySeed(
            identityHintId=store.next_id("hint"),
            productId=productId,
            distilledIdentity=distilledIdentity,
        )
        identity = self._MaybeEnrichIdentityWithLlm(
            identity,
            productName=productName,
            distilledIdentity=distilledIdentity,
            encyclopediaEvidence=encyclopediaEvidence,
            factTexts=factTexts,
        )
        composition = self._BuildCompositionLane(
            factTexts=factTexts,
            productFacts=productFacts,
            reconstructedTables=reconstructedTables,
            coiEvidence=coiEvidence,
        )
        understandingId = store.next_id("under")
        productUnderstanding = ProductUnderstandingPackage(
            understandingId=understandingId,
            productId=productId,
            sourceProductId=productId,
            productName=productName,
            shortDescription=shortDescription,
            classificationText=classificationText,
            reconstructedFactTexts=factTexts,
            reconstructedProductFacts=productFacts,
            distilledIdentity=distilledIdentity,
            identityHints=identity,
            compositionFacts=composition,
            coiEvidence=coiEvidence,
            encyclopediaEvidence=encyclopediaEvidence,
            routingTerms=self._RoutingTerms(
                productName=productName,
                distilledIdentity=distilledIdentity,
                identity=identity,
            ),
            unknowns=(
                ("reconstructed_product_facts",)
                if not productFacts
                else ()
            ),
        )
        store.put(
            "product_understanding",
            productUnderstanding.ToBlackboard(
                createdBy=self.component_name,
                createdAt=now_iso(),
            ),
        )
        self.WriteBlackBoard(understandingId)
        self.reason(
            "ProductUnderstandingPackage 생성: "
            f"facts={len(productFacts)}, fact_texts={len(factTexts)}, "
            f"encyclopedia={encyclopediaEvidence.qualityStatus}, "
            f"composition_terms={len(composition.compositionTerms)}."
        )

    def _BuildCoiEvidenceSet(
        self,
        store: BlackboardStore,
        *,
        productId: str,
        productName: str,
    ) -> CoiEvidenceSet:
        coiEvidenceId = store.next_id("coi")
        try:
            evidence = LoadCoiEvidence(
                caseIndex=None,
                productName=productName,
            )
        except RuntimeError as exc:
            return CoiEvidenceSet(
                coiEvidenceId=coiEvidenceId,
                productId=productId,
                error=str(exc),
            )
        if evidence is None:
            return CoiEvidenceSet(
                coiEvidenceId=coiEvidenceId,
                productId=productId,
            )
        return CoiEvidenceSet(
            coiEvidenceId=coiEvidenceId,
            productId=productId,
            matchedDocuments=(str(evidence.path),),
            matchedTexts=(evidence.text,),
            matchScores=(evidence.matchedScore,),
        )

    @staticmethod
    def _ReadTextTuple(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value.strip(),) if value.strip() else ()
        if not isinstance(value, list):
            return ()
        return tuple(str(item).strip() for item in value if str(item).strip())

    @staticmethod
    def _ReadFactTuple(value: object) -> tuple[dict[str, JsonValue], ...]:
        if not isinstance(value, list):
            return ()
        return tuple(
            ProductUnderstandingComponent._JsonDict(item)
            for item in value
            if isinstance(item, dict)
        )

    @staticmethod
    def _JsonDict(value: Mapping[object, object]) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {}
        for key, item in value.items():
            if isinstance(key, str):
                out[key] = ProductUnderstandingComponent._JsonValue(item)
        return out

    @staticmethod
    def _JsonValue(value: object) -> JsonValue:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [
                ProductUnderstandingComponent._JsonValue(item)
                for item in value
            ]
        if isinstance(value, dict):
            return ProductUnderstandingComponent._JsonDict(value)
        return str(value)

    @staticmethod
    def _FactTexts(productFacts: tuple[dict[str, JsonValue], ...]) -> tuple[str, ...]:
        texts: list[str] = []
        for fact in productFacts:
            field = str(
                fact.get("field_name")
                or fact.get("field")
                or fact.get("name")
                or ""
            ).strip()
            value = str(
                fact.get("normalized_value")
                or fact.get("value")
                or fact.get("text")
                or ""
            ).strip()
            if field and value:
                texts.append(f"{field}: {value}")
            elif value:
                texts.append(value)
        return tuple(texts)

    @staticmethod
    def _BuildIdentitySeed(
        *,
        identityHintId: str,
        productId: str,
        distilledIdentity: DistilledIdentityFacts,
    ) -> IdentityHintSet:
        return IdentityHintSet(
            identityHintId=identityHintId,
            productId=productId,
            commercialIdentity=distilledIdentity.commercialIdentity,
            normalizedTariffDescription=distilledIdentity.normalizedDescription,
            identityTerms=distilledIdentity.identityTerms,
            productFormTerms=distilledIdentity.productFormSignalTerms,
            confidence=0.4 if distilledIdentity.identityTerms else 0.0,
            understandingMode="wikipedia_distilled",
        )

    @staticmethod
    def _MaybeEnrichIdentityWithLlm(
        identity: IdentityHintSet,
        *,
        productName: str,
        distilledIdentity: DistilledIdentityFacts,
        encyclopediaEvidence: EncyclopediaEvidenceSet,
        factTexts: tuple[str, ...] = (),
    ) -> IdentityHintSet:
        """Overlay bounded LLM identity fields unless explicitly disabled.

        On by default (``ASAP_USE_LLM_UNDERSTANDING``). On LLM failure the regex identity is
        returned with the error recorded in the identity hint reasons. LLM output is
        already vocab-validated, so the overlay cannot introduce codes.
        """
        flag = (os.environ.get("ASAP_USE_LLM_UNDERSTANDING", "1") or "").strip().lower()
        if flag not in ("1", "true", "yes", "on"):
            return identity

        result = IdentityHintAgent().BuildIdentityFacts(
            productName=productName,
            distilledIdentity=distilledIdentity,
            encyclopediaEvidence=encyclopediaEvidence,
            factTexts=factTexts,
        )
        if result.get("understanding_mode") != "llm_json":
            return dataclasses.replace(
                identity,
                understandingMode=str(result.get("understanding_mode") or "regex_fallback"),
                llmError=str(result.get("llm_error") or ""),
            )
        overlay: dict[str, object] = {
            "productFormTerms": result["product_form_terms"],
            "domainHints": result["domain_hints"],
            "chapterHintTerms": result["chapter_hint_terms"],
            "chapterHintSourceTerms": result["chapter_hint_source_terms"],
            "chapterHintBasis": result["chapter_hint_basis"],
            "chapterHintStatus": result["chapter_hint_status"],
            "translatedProductName": result["translated_product_name"],
            "confidence": result["confidence"],
            "needsReview": result["needs_review"],
            "understandingMode": "llm_json",
            "llmError": "",
        }
        # Prefer non-empty LLM text/lists; keep the regex value otherwise.
        # Typed identity fields: vocab-grounded upstream; empty means the
        # evidence did not support a value, so the DTO default stands.
        if result.get("ingredient_class"):
            overlay["ingredientClass"] = result["ingredient_class"]
        if result.get("principal_ingredient_guess"):
            overlay["principalIngredientGuess"] = result["principal_ingredient_guess"]
        if result.get("accessory_ingredients"):
            overlay["accessoryIngredients"] = tuple(result["accessory_ingredients"])
        if result.get("food_form"):
            overlay["foodForm"] = result["food_form"]
        if result.get("processing_state"):
            overlay["processingState"] = result["processing_state"]
        if result["commercial_identity"]:
            overlay["commercialIdentity"] = result["commercial_identity"]
        if result["normalized_tariff_description"]:
            overlay["normalizedTariffDescription"] = result["normalized_tariff_description"]
        if result["identity_terms"]:
            overlay["identityTerms"] = result["identity_terms"]
        return dataclasses.replace(identity, **overlay)

    @staticmethod
    def _BuildCompositionLane(
        *,
        factTexts: tuple[str, ...],
        productFacts: tuple[dict[str, JsonValue], ...],
        coiEvidence: CoiEvidenceSet,
        reconstructedTables: tuple[dict[str, JsonValue], ...] = (),
    ) -> CompositionFactSet:
        # COI (식품원재료풀이) is composition evidence — it belongs to this lane,
        # not the identity lane. Feed its matched texts into %-parsing and terms.
        coiTexts = tuple(coiEvidence.matchedTexts)
        tableTexts = ProductUnderstandingComponent._ReconstructedTableTexts(
            reconstructedTables,
        )
        factTextValues = ProductUnderstandingComponent._FactTexts(productFacts)
        text = "\n".join([*factTexts, *factTextValues, *tableTexts, *coiTexts])
        ingredientEntries = ProductUnderstandingComponent._BuildIngredientEntries(
            productFacts=productFacts,
            reconstructedTables=reconstructedTables,
        )
        # COI 구조화 합류 (ASAP_COI_COMPOSITION, 기본 ON): 원료풀이 표를
        # 표기순 엔트리로 파싱해 composition lane에 공급 — 텍스트 잡탕이
        # 아니라 질문이 소비 가능한 구조로. 라벨 엔트리가 없으면 주 소스로
        # 승격(scope=product), 있으면 보조(scope=coi) 병기.
        if (os.environ.get("ASAP_COI_COMPOSITION", "1") or "1").strip() != "0":
            try:
                from agents.coi_loader import ParseCoiComposition
                from pathlib import Path as _P

                coi_entries: list[dict[str, JsonValue]] = []
                for doc in coiEvidence.matchedDocuments[:1]:
                    for e in ParseCoiComposition(_P(doc)):
                        coi_entries.append({
                            "scope": "product" if not ingredientEntries else "coi",
                            "ingredient_name": e["ingredient_name"],
                            "component": e.get("component") or "",
                            "percent": e.get("percent"),
                            "order_index": e["order_index"],
                            "origin": e.get("origin") or "",
                            "source": "coi",
                        })
                if coi_entries:
                    ingredientEntries = [*ingredientEntries, *coi_entries]
            except Exception:  # noqa: BLE001 — COI 실패는 무증거일 뿐
                pass
        percentages = ProductUnderstandingComponent._IngredientPercentagesFromEntries(
            ingredientEntries,
        )
        componentCompositions = ProductUnderstandingComponent._BuildComponentCompositions(
            productFacts=productFacts,
            reconstructedTables=reconstructedTables,
            ingredientEntries=ingredientEntries,
        )
        principalCandidates = ProductUnderstandingComponent._BuildPrincipalCandidates(
            ingredientEntries,
        )
        principalStatus = ProductUnderstandingComponent._PrincipalStatus(
            principalCandidates,
        )
        # COI 교차 검증 승격: 라벨 1위 후보와 COI 1위 성분의 정규화 토큰이
        # 겹치면 독립 2근거 일치 → confirmed 승격. 한↔영 혼재 파일이 있어
        # 겹침 실패는 conflict가 아니라 '비교 불가'(중립)로 둔다.
        if principalStatus != "confirmed" and principalCandidates:
            _tok = lambda s: {w.lower() for w in re.findall(r"[A-Za-z가-힣]+", str(s or "")) if len(w) >= 2}
            coi_first = next(
                (e for e in ingredientEntries
                 if e.get("source") == "coi" and int(e.get("order_index") or 0) == 1),
                None,
            )
            if coi_first is not None:
                top = principalCandidates[0]
                overlap = _tok(top.get("ingredient_name")) & _tok(coi_first.get("ingredient_name"))
                if overlap:
                    principalStatus = "confirmed"
                    top = dict(top)
                    top["basis"] = f"{top.get('basis')}+coi_cross_check"
                    top["confidence"] = max(float(top.get("confidence") or 0), 0.85)
                    principalCandidates = [top, *principalCandidates[1:]]
        principalIngredient = (
            str(principalCandidates[0].get("ingredient_name") or "")
            if principalStatus == "confirmed" and principalCandidates
            else ""
        )

        allergenTexts = [
            item
            for item in factTexts
            if ALLERGEN_RE.search(item)
        ]
        missing: list[str] = []
        if not percentages:
            missing.append("ingredient_percentages")

        compositionTerms = ProductUnderstandingComponent._CompositionTerms(
            productFacts=productFacts,
            reconstructedTables=reconstructedTables,
            factTexts=factTexts,
            coiTexts=coiTexts,
        )
        ingredientClasses = ProductUnderstandingComponent._BuildIngredientClasses(
            ingredientEntries=ingredientEntries,
            compositionTerms=compositionTerms,
        )
        processingState = ProductUnderstandingComponent._BuildProcessingState(
            factTexts=(
                *factTextValues,
                *tableTexts,
                *factTexts,
                *coiTexts,
            ),
        )
        return CompositionFactSet(
            processingState=processingState,
            principalIngredient=principalIngredient,
            principalIngredientStatus=principalStatus,
            principalIngredientCandidates=tuple(principalCandidates[:10]),
            ingredientClasses=ingredientClasses,
            ingredientEntries=tuple(ingredientEntries[:80]),
            ingredientPercentages=tuple(percentages[:20]),
            componentCompositions=tuple(componentCompositions[:20]),
            compositionTerms=compositionTerms,
            compositionBasis="label" if percentages else ("coi_text" if coiTexts else "label_text_no_percent"),
            containsWrapperOrDough=bool(WRAPPER_RE.search(text)),
            containsSauceOrBroth=bool(SAUCE_BROTH_RE.search(text)),
            allergenTermsExcluded=tuple(allergenTexts[:20]),
            missingCompositionFacts=tuple(missing),
        )

    @staticmethod
    def _CompositionPercentageTexts(
        productFacts: tuple[dict[str, JsonValue], ...],
        *,
        productLevelOnly: bool = False,
    ) -> tuple[str, ...]:
        texts: list[str] = []
        for fact in productFacts:
            field = str(
                fact.get("field_name")
                or fact.get("field")
                or fact.get("name")
                or ""
            ).strip()
            value = str(
                fact.get("normalized_value")
                or fact.get("value")
                or fact.get("text")
                or ""
            ).strip()
            if not field or not value:
                continue
            if not ProductUnderstandingComponent._IsCompositionFieldName(field):
                continue
            if (
                productLevelOnly
                and not ProductUnderstandingComponent._IsProductLevelCompositionFieldName(field)
            ):
                continue
            texts.append(value)
        return tuple(texts)

    @staticmethod
    def _ReconstructedTableTexts(
        reconstructedTables: tuple[dict[str, JsonValue], ...],
    ) -> tuple[str, ...]:
        texts: list[str] = []
        for table in reconstructedTables:
            tableName = str(table.get("table_name") or "").strip()
            rows = table.get("rows")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                field = str(row.get("field_name") or "").strip()
                value = str(row.get("normalized_value") or "").strip()
                if not field or not value:
                    continue
                prefix = f"{tableName} / " if tableName else ""
                texts.append(f"{prefix}{field}: {value}")
        return tuple(texts)

    @staticmethod
    def _CompositionTerms(
        *,
        productFacts: tuple[dict[str, JsonValue], ...],
        reconstructedTables: tuple[dict[str, JsonValue], ...],
        factTexts: tuple[str, ...],
        coiTexts: tuple[str, ...],
    ) -> tuple[str, ...]:
        terms: list[str] = []
        for fact in productFacts:
            field = ProductUnderstandingComponent._ReadTextField(fact, "field_name")
            value = ProductUnderstandingComponent._ReadTextField(fact, "normalized_value")
            if field and value and ProductUnderstandingComponent._IsCompositionFieldName(field):
                terms.append(f"{field}: {value}")

        for table in reconstructedTables:
            tableName = str(table.get("table_name") or "").strip()
            rows = table.get("rows")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                field = ProductUnderstandingComponent._ReadTextField(row, "field_name")
                value = ProductUnderstandingComponent._ReadTextField(row, "normalized_value")
                if not field or not value:
                    continue
                if not ProductUnderstandingComponent._IsCompositionFieldName(field):
                    continue
                prefix = f"{tableName} / " if tableName else ""
                terms.append(f"{prefix}{field}: {value}")

        for text in factTexts:
            if ProductUnderstandingComponent._LooksLikeCompositionText(text):
                terms.append(text)
        terms.extend(coiTexts)
        return ProductUnderstandingComponent._DedupStrings(terms, limit=80)

    @staticmethod
    def _LooksLikeCompositionText(text: str) -> bool:
        value = str(text or "").strip()
        if not value or ALLERGEN_RE.search(value) or ADMIN_LABEL_LINE_RE.search(value):
            return False
        fieldName = value.split(":", 1)[0].strip() if ":" in value else value
        return ProductUnderstandingComponent._IsCompositionFieldName(fieldName)

    @staticmethod
    def _BuildIngredientClasses(
        *,
        ingredientEntries: list[dict[str, JsonValue]],
        compositionTerms: tuple[str, ...],
    ) -> tuple[str, ...]:
        evidenceTexts = [
            str(entry.get("ingredient_name") or "")
            for entry in ingredientEntries
            if str(entry.get("ingredient_name") or "").strip()
        ]
        if not evidenceTexts:
            evidenceTexts.extend(compositionTerms)
        classes: list[str] = []
        for className, terms in INGREDIENT_CLASS_RULES:
            if any(
                ProductUnderstandingComponent._ContainsTerm(text, term)
                for text in evidenceTexts
                for term in terms
            ):
                classes.append(className)
        return tuple(classes)

    @staticmethod
    def _BuildProcessingState(*, factTexts: tuple[str, ...]) -> str:
        states: list[str] = []
        for stateName, terms in PROCESSING_STATE_RULES:
            if any(
                ProductUnderstandingComponent._ContainsTerm(text, term)
                for text in factTexts
                for term in terms
            ):
                states.append(stateName)
        return " ".join(states[:4]) if states else "unknown"

    @staticmethod
    def _IngredientTermAliases(term: str) -> tuple[str, ...]:
        aliases: list[str] = []
        for marker, values in INGREDIENT_TERM_ALIASES:
            if ProductUnderstandingComponent._ContainsTerm(term, marker):
                for value in values:
                    if value not in aliases:
                        aliases.append(value)
        return tuple(aliases)

    @staticmethod
    def _ContainsTerm(text: str, term: str) -> bool:
        return str(term).lower() in str(text).lower()

    @staticmethod
    def _BuildIngredientEntries(
        *,
        productFacts: tuple[dict[str, JsonValue], ...],
        reconstructedTables: tuple[dict[str, JsonValue], ...],
    ) -> list[dict[str, JsonValue]]:
        entries: list[dict[str, JsonValue]] = []
        for fact in productFacts:
            field = ProductUnderstandingComponent._ReadTextField(fact, "field_name")
            value = ProductUnderstandingComponent._ReadTextField(fact, "normalized_value")
            ProductUnderstandingComponent._ExtendIngredientEntries(
                entries,
                fieldName=field,
                value=value,
                sourceRefs=ProductUnderstandingComponent._ReadSourceRefs(fact),
                sourceKind="product_fact",
            )

        for table in reconstructedTables:
            rows = table.get("rows")
            tableRefs = ProductUnderstandingComponent._ReadSourceRefs(table)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                field = ProductUnderstandingComponent._ReadTextField(row, "field_name")
                value = ProductUnderstandingComponent._ReadTextField(
                    row,
                    "normalized_value",
                )
                sourceRefs = ProductUnderstandingComponent._ReadSourceRefs(row) or tableRefs
                ProductUnderstandingComponent._ExtendIngredientEntries(
                    entries,
                    fieldName=field,
                    value=value,
                    sourceRefs=sourceRefs,
                    sourceKind="reconstructed_table",
                )
        return ProductUnderstandingComponent._DedupIngredientEntries(entries)

    @staticmethod
    def _ExtendIngredientEntries(
        entries: list[dict[str, JsonValue]],
        *,
        fieldName: str,
        value: str,
        sourceRefs: tuple[str, ...],
        sourceKind: str,
    ) -> None:
        if not fieldName or not value:
            return
        if not ProductUnderstandingComponent._IsCompositionFieldName(fieldName):
            return
        componentName = ProductUnderstandingComponent._ReadComponentName(fieldName)
        scope = "component" if componentName else "product"
        for orderIndex, segment in enumerate(
            ProductUnderstandingComponent._SplitTopLevelIngredients(value),
            start=1,
        ):
            ingredientName = ProductUnderstandingComponent._ReadIngredientName(segment)
            if not ingredientName:
                continue
            percentage = ProductUnderstandingComponent._ReadTopLevelPercentage(segment)
            entry: dict[str, JsonValue] = {
                "ingredient_name": ingredientName,
                "order_index": orderIndex,
                "scope": scope,
                "component_name": componentName,
                "source_field_name": fieldName,
                "source_refs": list(sourceRefs),
                "source_kind": sourceKind,
            }
            if percentage is not None:
                entry["percent"] = percentage
            entries.append(entry)

    @staticmethod
    def _SplitTopLevelIngredients(text: str) -> tuple[str, ...]:
        parts: list[str] = []
        current: list[str] = []
        depth = 0
        for character in text:
            if character in "([{":
                depth += 1
            elif character in ")]}":
                depth = max(0, depth - 1)
            if character in ",，、" and depth == 0:
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                continue
            current.append(character)
        part = "".join(current).strip()
        if part:
            parts.append(part)
        return tuple(parts)

    @staticmethod
    def _ReadIngredientName(segment: str) -> str:
        percentage = ProductUnderstandingComponent._ReadTopLevelPercentageEntry(segment)
        if percentage is not None:
            return str(percentage.get("term") or "").strip()
        name = re.split(r"[\(\[\{（［]", segment, maxsplit=1)[0]
        name = re.sub(r"\d+(?:[.,]\d+)?\s*%", "", name)
        return " ".join(name.strip(" ,:/·-").split())

    @staticmethod
    def _ReadTopLevelPercentage(segment: str) -> JsonValue | None:
        percentage = ProductUnderstandingComponent._ReadTopLevelPercentageEntry(segment)
        if percentage is None:
            return None
        return percentage.get("percent")

    @staticmethod
    def _ReadTopLevelPercentageEntry(segment: str) -> dict[str, JsonValue] | None:
        percentages = ProductUnderstandingComponent._ExtractIngredientPercentages(segment)
        return percentages[0] if percentages else None

    @staticmethod
    def _DedupIngredientEntries(
        entries: list[dict[str, JsonValue]],
    ) -> list[dict[str, JsonValue]]:
        out: list[dict[str, JsonValue]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for entry in entries:
            key = (
                str(entry.get("ingredient_name") or "").lower(),
                str(entry.get("scope") or ""),
                str(entry.get("component_name") or ""),
                str(entry.get("order_index") or ""),
                str(entry.get("percent") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
        return out

    @staticmethod
    def _IngredientPercentagesFromEntries(
        ingredientEntries: list[dict[str, JsonValue]],
    ) -> list[dict[str, JsonValue]]:
        percentages: list[dict[str, JsonValue]] = []
        seen: set[tuple[str, str]] = set()
        for entry in ingredientEntries:
            percent = entry.get("percent")
            if percent is None:
                continue
            term = str(entry.get("ingredient_name") or "").strip()
            key = (term.lower(), str(percent))
            if term and key not in seen:
                item: dict[str, JsonValue] = {"term": term, "percent": percent}
                aliases = ProductUnderstandingComponent._IngredientTermAliases(term)
                if aliases:
                    item["term_aliases"] = list(aliases)
                percentages.append(item)
                seen.add(key)
        return percentages

    @staticmethod
    def _BuildComponentCompositions(
        *,
        productFacts: tuple[dict[str, JsonValue], ...],
        reconstructedTables: tuple[dict[str, JsonValue], ...],
        ingredientEntries: list[dict[str, JsonValue]],
    ) -> list[dict[str, JsonValue]]:
        components: dict[str, dict[str, JsonValue]] = {}
        for entry in ingredientEntries:
            componentName = str(entry.get("component_name") or "").strip()
            if not componentName:
                continue
            component = components.setdefault(
                componentName,
                {
                    "component_name": componentName,
                    "ingredient_names": [],
                    "source_refs": [],
                },
            )
            ingredientNames = component.setdefault("ingredient_names", [])
            if isinstance(ingredientNames, list):
                ingredientName = str(entry.get("ingredient_name") or "").strip()
                if ingredientName and ingredientName not in ingredientNames:
                    ingredientNames.append(ingredientName)
            ProductUnderstandingComponent._MergeSourceRefs(
                component,
                ProductUnderstandingComponent._ReadEntrySourceRefs(entry),
            )

        ProductUnderstandingComponent._ApplyComponentFacts(
            components,
            productFacts,
        )
        ProductUnderstandingComponent._ApplyComponentTableRows(
            components,
            reconstructedTables,
        )
        return [
            components[key]
            for key in sorted(components)
        ]

    @staticmethod
    def _ApplyComponentFacts(
        components: dict[str, dict[str, JsonValue]],
        productFacts: tuple[dict[str, JsonValue], ...],
    ) -> None:
        for fact in productFacts:
            field = ProductUnderstandingComponent._ReadTextField(fact, "field_name")
            value = ProductUnderstandingComponent._ReadTextField(fact, "normalized_value")
            sourceRefs = ProductUnderstandingComponent._ReadSourceRefs(fact)
            componentName = ProductUnderstandingComponent._ReadComponentName(field)
            if componentName:
                component = components.setdefault(
                    componentName,
                    {"component_name": componentName, "ingredient_names": [], "source_refs": []},
                )
                ProductUnderstandingComponent._MergeSourceRefs(component, sourceRefs)
                compactField = field.replace(" ", "")
                if "식품유형" in compactField or "식품의유형" in compactField:
                    component["food_type"] = value
                if "내용량" in compactField or "중량" in compactField:
                    ProductUnderstandingComponent._SetComponentWeight(
                        component,
                        value,
                        "",
                    )
            ProductUnderstandingComponent._ApplyComponentWeightsFromText(
                components,
                value,
                sourceRefs,
            )

    @staticmethod
    def _ApplyComponentTableRows(
        components: dict[str, dict[str, JsonValue]],
        reconstructedTables: tuple[dict[str, JsonValue], ...],
    ) -> None:
        for table in reconstructedTables:
            rows = table.get("rows")
            tableRefs = ProductUnderstandingComponent._ReadSourceRefs(table)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                field = ProductUnderstandingComponent._ReadTextField(row, "field_name")
                value = ProductUnderstandingComponent._ReadTextField(
                    row,
                    "normalized_value",
                )
                unit = ProductUnderstandingComponent._ReadTextField(row, "unit")
                sourceRefs = ProductUnderstandingComponent._ReadSourceRefs(row) or tableRefs
                componentName = ProductUnderstandingComponent._ReadComponentFromContentField(
                    field,
                )
                if componentName:
                    component = components.setdefault(
                        componentName,
                        {
                            "component_name": componentName,
                            "ingredient_names": [],
                            "source_refs": [],
                        },
                    )
                    ProductUnderstandingComponent._SetComponentWeight(
                        component,
                        value,
                        unit,
                    )
                    ProductUnderstandingComponent._MergeSourceRefs(
                        component,
                        sourceRefs,
                    )
                ProductUnderstandingComponent._ApplyComponentWeightsFromText(
                    components,
                    f"{field} {value} {unit}",
                    sourceRefs,
                )

    @staticmethod
    def _ApplyComponentWeightsFromText(
        components: dict[str, dict[str, JsonValue]],
        text: str,
        sourceRefs: tuple[str, ...],
    ) -> None:
        for match in CONTENT_WEIGHT_RE.finditer(text):
            componentName = " ".join((match.group("component") or "").split()).strip(" ,:/")
            amount = ProductUnderstandingComponent._ReadNumericValue(
                match.group("amount"),
            )
            unit = (match.group("unit") or "").lower()
            if not componentName or amount is None:
                continue
            if (
                re.search(r"[A-Za-z가-힣]", componentName) is None
                or componentName.lower() in {"g", "kg", "ml", "l"}
                or ProductUnderstandingComponent._IsComponentWeightNoise(
                    componentName,
                    text,
                )
            ):
                continue
            component = components.setdefault(
                componentName,
                {"component_name": componentName, "ingredient_names": [], "source_refs": []},
            )
            component["content_weight"] = amount
            component["content_weight_unit"] = unit
            ProductUnderstandingComponent._MergeSourceRefs(component, sourceRefs)

    @staticmethod
    def _IsComponentWeightNoise(componentName: str, text: str) -> bool:
        normalizedName = componentName.replace(" ", "")
        if normalizedName in COMPONENT_WEIGHT_NOISE_NAMES:
            return True
        return bool(NUTRITION_FIELD_RE.search(text))

    @staticmethod
    def _SetComponentWeight(
        component: dict[str, JsonValue],
        value: str,
        unit: str,
    ) -> None:
        amount = ProductUnderstandingComponent._ReadNumericValue(value)
        if amount is None:
            return
        component["content_weight"] = amount
        if unit:
            component["content_weight_unit"] = unit

    @staticmethod
    def _BuildPrincipalCandidates(
        ingredientEntries: list[dict[str, JsonValue]],
    ) -> list[dict[str, JsonValue]]:
        productEntries = [
            entry
            for entry in ingredientEntries
            if entry.get("scope") == "product"
            and str(entry.get("ingredient_name") or "").strip()
        ]
        candidatesByName: dict[str, dict[str, JsonValue]] = {}
        if productEntries:
            firstEntry = min(
                productEntries,
                key=lambda entry: int(entry.get("order_index") or 9999),
            )
            ProductUnderstandingComponent._AddPrincipalCandidate(
                candidatesByName,
                firstEntry,
                basis="ingredient_order_first",
                confidence=0.65,
            )
        for entry in productEntries:
            percent = entry.get("percent")
            if not isinstance(percent, (int, float)):
                continue
            confidence = 0.9 if percent >= 15 else 0.35
            ProductUnderstandingComponent._AddPrincipalCandidate(
                candidatesByName,
                entry,
                basis="explicit_percent",
                confidence=confidence,
                percent=percent,
                role="minor_ingredient" if percent < 10 else "major_ingredient",
            )
        if not productEntries:
            for entry in ingredientEntries:
                if entry.get("scope") != "component":
                    continue
                percent = entry.get("percent")
                if not isinstance(percent, (int, float)):
                    continue
                ProductUnderstandingComponent._AddPrincipalCandidate(
                    candidatesByName,
                    entry,
                    basis="component_explicit_percent",
                    confidence=0.45,
                    percent=percent,
                    role="component_ingredient",
                )
        return sorted(
            candidatesByName.values(),
            key=lambda item: (
                -float(item.get("confidence") or 0.0),
                -float(item.get("percent") or 0.0),
                int(item.get("order_index") or 9999),
                str(item.get("ingredient_name") or ""),
            ),
        )

    @staticmethod
    def _AddPrincipalCandidate(
        candidatesByName: dict[str, dict[str, JsonValue]],
        entry: dict[str, JsonValue],
        *,
        basis: str,
        confidence: float,
        percent: float | None = None,
        role: str = "",
    ) -> None:
        ingredientName = str(entry.get("ingredient_name") or "").strip()
        if not ingredientName:
            return
        key = ingredientName.lower()
        candidate = candidatesByName.setdefault(
            key,
            {
                "ingredient_name": ingredientName,
                "confidence": confidence,
                "basis": basis,
                "order_index": entry.get("order_index") or 9999,
                "scope": str(entry.get("scope") or "product"),
                "component_name": str(entry.get("component_name") or ""),
                "source_refs": [],
            },
        )
        candidate["confidence"] = max(
            float(candidate.get("confidence") or 0.0),
            confidence,
        )
        basisText = str(candidate.get("basis") or "")
        if basis not in basisText.split("+"):
            candidate["basis"] = "+".join(filter(None, [basisText, basis]))
        if percent is not None:
            candidate["percent"] = percent
        if role:
            candidate["role"] = role
        ProductUnderstandingComponent._MergeSourceRefs(
            candidate,
            ProductUnderstandingComponent._ReadEntrySourceRefs(entry),
        )

    @staticmethod
    def _PrincipalStatus(candidates: list[dict[str, JsonValue]]) -> str:
        if not candidates:
            return "unknown"
        productCandidates = [
            candidate
            for candidate in candidates
            if str(candidate.get("scope") or "product") == "product"
        ]
        if not productCandidates:
            return "unknown"
        topConfidence = float(productCandidates[0].get("confidence") or 0.0)
        return "confirmed" if topConfidence >= 0.8 else "ambiguous"

    @staticmethod
    def _ReadTextField(value: Mapping[str, JsonValue], key: str) -> str:
        item = value.get(key)
        return str(item or "").strip()

    @staticmethod
    def _ReadSourceRefs(value: Mapping[str, JsonValue]) -> tuple[str, ...]:
        refs = value.get("source_refs")
        if not isinstance(refs, list):
            return ()
        return tuple(str(ref).strip() for ref in refs if str(ref).strip())

    @staticmethod
    def _ReadEntrySourceRefs(entry: Mapping[str, JsonValue]) -> tuple[str, ...]:
        return ProductUnderstandingComponent._ReadSourceRefs(entry)

    @staticmethod
    def _ReadComponentName(fieldName: str) -> str:
        match = COMPONENT_NAME_RE.search(fieldName)
        if match is None:
            return ""
        return " ".join((match.group("component") or "").strip().split())

    @staticmethod
    def _ReadComponentFromContentField(fieldName: str) -> str:
        normalizedFieldName = " ".join(fieldName.split())
        for marker in ("내용량", "중량", "용량"):
            if marker not in normalizedFieldName:
                continue
            componentName = normalizedFieldName.split(marker, 1)[0].strip(" :：-/")
            if componentName:
                return componentName
        return ProductUnderstandingComponent._ReadComponentName(fieldName)

    @staticmethod
    def _ReadNumericValue(value: str) -> JsonValue | None:
        match = re.search(r"\d+(?:[.,]\d+)?", value or "")
        if match is None:
            return None
        numberText = match.group(0).replace(",", ".")
        try:
            number = float(numberText)
        except ValueError:
            return numberText
        return int(number) if number.is_integer() else number

    @staticmethod
    def _MergeSourceRefs(
        target: dict[str, JsonValue],
        sourceRefs: tuple[str, ...],
    ) -> None:
        current = target.get("source_refs")
        refs = [str(ref) for ref in current] if isinstance(current, list) else []
        for sourceRef in sourceRefs:
            if sourceRef not in refs:
                refs.append(sourceRef)
        target["source_refs"] = refs

    @staticmethod
    def _ExtractIngredientPercentages(text: str) -> list[dict[str, JsonValue]]:
        percentages: list[dict[str, JsonValue]] = []
        seenPercentages: set[tuple[str, str]] = set()
        for match in PERCENT_RE.finditer(text):
            if ProductUnderstandingComponent._IsNestedPercentage(
                text,
                match.start("percent"),
            ):
                continue
            term = " ".join((match.group("term") or "").split())[-40:].strip(" ,:/")
            percentRaw = (match.group("percent") or "").replace(",", ".")
            try:
                percent: JsonValue = float(percentRaw)
            except ValueError:
                percent = percentRaw
            key = (term.lower(), str(percent))
            if term and key not in seenPercentages and not ORIGIN_TERM_RE.search(term):
                percentages.append({"term": term, "percent": percent})
                seenPercentages.add(key)
        return percentages

    @staticmethod
    def _IsProductLevelCompositionFieldName(fieldName: str) -> bool:
        if not ProductUnderstandingComponent._IsCompositionFieldName(fieldName):
            return False
        # 괄호가 붙은 원재료 필드는 구성품 scoped fact다. 함량은 보존하되
        # 전체 상품의 주성분으로 승격하지 않는다.
        return not re.search(r"[\(\[（［].+[\)\]）］]", fieldName)

    @staticmethod
    def _IsCompositionFieldName(fieldName: str) -> bool:
        compactFieldName = fieldName.replace(" ", "").lower()
        if NUTRITION_FIELD_RE.search(compactFieldName):
            return False
        return any(
            marker.lower() in compactFieldName
            for marker in COMPOSITION_PERCENT_FIELD_MARKERS
        )

    @staticmethod
    def _IsNestedPercentage(text: str, index: int) -> bool:
        depth = 0
        for character in text[:index]:
            if character in "([{":
                depth += 1
            elif character in ")]}":
                depth = max(0, depth - 1)
        return depth > 0

    @staticmethod
    def _DedupStrings(values: list[str] | tuple[str, ...], *, limit: int) -> tuple[str, ...]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= limit:
                break
        return tuple(out)

    @staticmethod
    def _RoutingTerms(
        *,
        productName: str,
        distilledIdentity: DistilledIdentityFacts,
        identity: IdentityHintSet,
    ) -> tuple[str, ...]:
        terms: list[str] = []
        for value in (
            productName,
            identity.commercialIdentity,
            identity.translatedProductName,
            identity.normalizedTariffDescription,
            *identity.productFormTerms,
            *identity.domainHints,
            *identity.chapterHintTerms,
            *identity.chapterHintSourceTerms,
            *distilledIdentity.productFormSignalTerms,
            *distilledIdentity.processingSignalTerms,
            *identity.identityTerms,
        ):
            text = str(value).strip()
            if text and text not in terms:
                terms.append(text)
        return tuple(terms[:80])
