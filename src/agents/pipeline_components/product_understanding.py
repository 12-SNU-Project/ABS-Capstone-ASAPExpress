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
    r"(?P<term>[A-Za-z가-힣][A-Za-z가-힣 /·._-]{0,39}?)\s*(?P<percent>\d+(?:[.,]\d+)?)\s*%",
)
WRAPPER_RE = re.compile(r"피|만두피|도우|반죽|wrapper|dough|pastry", re.I)
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
        # §13(b): OCR composition lines, selectively. Full raw-OCR re-injection is
        # forbidden (designer rule); only ingredient/percentage lines, capped, so
        # detail-page composition tables still reach the understanding stage.
        factTexts = (*factTexts, *self._OcrCompositionLines(observedFacts, factTexts))
        productFacts = self._ReadFactTuple(
            observedFacts.get("reconstructed_product_facts") or [],
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
        )
        composition = self._BuildCompositionLane(
            factTexts=factTexts,
            productFacts=productFacts,
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

    _OCR_COMPOSITION_LINE_RE = re.compile(
        r"원재료|원료|성분|함량|배합|재료명|\d+(?:[.,]\d+)?\s*%",
    )

    @classmethod
    def _OcrCompositionLines(
        cls,
        observedFacts: dict[str, JsonValue],
        existingFactTexts: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Composition-looking lines from observed ocr_text (capped, dedup)."""
        raw = observedFacts.get("ocr_text")
        if isinstance(raw, list):
            text = "\n".join(str(item) for item in raw)
        else:
            text = str(raw or "")
        if not text.strip():
            return ()
        existing = {line.strip() for line in existingFactTexts}
        out: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or len(line) < 4 or line in existing:
                continue
            if not cls._OCR_COMPOSITION_LINE_RE.search(line):
                continue
            out.append(line[:200])
            if len(out) >= 8:
                break
        return tuple(out)

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
    ) -> CompositionFactSet:
        # COI (식품원재료풀이) is composition evidence — it belongs to this lane,
        # not the identity lane. Feed its matched texts into %-parsing and terms.
        coiTexts = tuple(coiEvidence.matchedTexts)
        text = "\n".join([*factTexts, *ProductUnderstandingComponent._FactTexts(productFacts), *coiTexts])
        percentages: list[dict[str, JsonValue]] = []
        seenPercentages: set[tuple[str, str]] = set()
        for match in PERCENT_RE.finditer(text):
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

        allergenTexts = [
            item
            for item in factTexts
            if ALLERGEN_RE.search(item)
        ]
        missing: list[str] = []
        if not percentages:
            missing.append("ingredient_percentages")

       
        compositionTerms = ProductUnderstandingComponent._DedupStrings(
            [
                *ProductUnderstandingComponent._FactTexts(productFacts),
                *factTexts,
                *coiTexts,
            ],
            limit=80,
        )
        return CompositionFactSet(
            processingState="processed_or_prepared" if processingTerms else "unknown",
            principalIngredient=(
                str(percentages[0].get("term") or "")
                if percentages
                else ""
            ),
            ingredientClasses=(),
            ingredientPercentages=tuple(percentages[:20]),
            compositionTerms=compositionTerms,
            processingTerms=identity.charp,
            compositionBasis="label" if percentages else ("coi_text" if coiTexts else "label_text_no_percent"),
            containsWrapperOrDough=bool(WRAPPER_RE.search(text)),
            containsSauceOrBroth=bool(SAUCE_BROTH_RE.search(text)),
            allergenTermsExcluded=tuple(allergenTexts[:20]),
            missingCompositionFacts=tuple(missing),
        )

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
