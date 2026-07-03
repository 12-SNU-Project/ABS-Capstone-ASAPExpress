from pytest import MonkeyPatch

from agents.llm_agents import identity_hint_agent
from agents.pipeline_components import product_understanding
from agents.pipeline_dto import (
    DistilledIdentityFacts,
    EncyclopediaEvidenceSet,
    IdentityHintSet,
)


class FakeLlmResponse:
    generatedText: str = """{
      "translated_product_name": "stir-fried octopus",
      "commercial_identity": "Nakji-bokkeum",
      "normalized_tariff_description": "prepared stir-fried octopus",
      "identity_terms": ["octopus"],
      "product_form_terms": ["prepared seafood"],
      "domain_hints": ["food", "animal_origin"],
      "chapter_hint_terms": ["prepared seafood"],
      "chapter_hint_source_terms": ["octopus"],
      "chapter_hint_basis": "from_chapter_context",
      "chapter_hint_status": "enabled",
      "confidence": 0.9,
      "needs_review": false
    }"""


class FakeRuntimeAdapter:
    def Generate(self, request: object) -> FakeLlmResponse:
        del request
        return FakeLlmResponse()


class FakeIdentityHintAgent:
    calls: int = 0

    def BuildIdentityFacts(
        self,
        *,
        productName: str,
        distilledIdentity: DistilledIdentityFacts,
        encyclopediaEvidence: EncyclopediaEvidenceSet,
    ) -> dict[str, object]:
        del productName, distilledIdentity, encyclopediaEvidence
        type(self).calls += 1
        return {
            "understanding_mode": "llm_json",
            "product_form_terms": ("prepared seafood",),
            "domain_hints": ("food", "animal_origin"),
            "chapter_hint_terms": ("prepared fish",),
            "chapter_hint_source_terms": ("fish",),
            "chapter_hint_basis": "from_chapter_context",
            "chapter_hint_status": "enabled",
            "translated_product_name": "prepared seafood sauce",
            "confidence": 0.8,
            "needs_review": False,
            "commercial_identity": "prepared seafood",
            "normalized_tariff_description": "prepared seafood sauce",
            "identity_terms": ("seafood",),
        }


def _BuildSeedIdentity() -> IdentityHintSet:
    return IdentityHintSet(
        identityHintId="hint_001",
        productId="prod_001",
        commercialIdentity="주꾸미 볶음",
    )


def _BuildDistilledIdentity() -> DistilledIdentityFacts:
    return DistilledIdentityFacts(
        distilledIdentityId="distid_001",
        productId="prod_001",
        sourceEncyclopediaEvidenceId="ency_001",
        commercialIdentity="octopus",
        normalizedDescription="octopus prepared seafood",
        identityTerms=("octopus", "prepared", "seafood"),
        productFormSignalTerms=("seafood",),
        processingSignalTerms=("prepared",),
    )


def test_identity_hint_agent_runs_by_default(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("ASAP_USE_LLM_UNDERSTANDING", raising=False)
    FakeIdentityHintAgent.calls = 0
    monkeypatch.setattr(
        product_understanding,
        "IdentityHintAgent",
        FakeIdentityHintAgent,
    )

    identity = product_understanding.ProductUnderstandingComponent._MaybeEnrichIdentityWithLlm(
        _BuildSeedIdentity(),
        productName="주꾸미 볶음",
        distilledIdentity=_BuildDistilledIdentity(),
        encyclopediaEvidence=EncyclopediaEvidenceSet(
            encyclopediaEvidenceId="ency_001",
            productId="prod_001",
            query="주꾸미 볶음",
            configured=True,
        ),
    )

    assert FakeIdentityHintAgent.calls == 1
    assert identity.understandingMode == "llm_json"
    assert identity.chapterHintTerms == ("prepared fish",)
    assert identity.translatedProductName == "prepared seafood sauce"
    assert identity.compositionTerms == ()
    assert identity.processingTerms == ()


def test_identity_hint_agent_does_not_reference_missing_short_description(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity_hint_agent, "_adapter_cache", [FakeRuntimeAdapter()])
    monkeypatch.setattr(identity_hint_agent, "_chapter_context", lambda: "")

    result = identity_hint_agent.IdentityHintAgent().BuildIdentityFacts(
        productName="낙지볶음",
        distilledIdentity=_BuildDistilledIdentity(),
        encyclopediaEvidence=EncyclopediaEvidenceSet(
            encyclopediaEvidenceId="ency_001",
            productId="prod_001",
            query="낙지볶음",
            configured=True,
        ),
    )

    assert result["understanding_mode"] == "llm_json"
    assert result["translated_product_name"] == "stir-fried octopus"
    assert result["chapter_hint_terms"] == ("prepared seafood",)


def test_identity_hint_agent_can_be_disabled(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("ASAP_USE_LLM_UNDERSTANDING", "0")
    FakeIdentityHintAgent.calls = 0
    monkeypatch.setattr(
        product_understanding,
        "IdentityHintAgent",
        FakeIdentityHintAgent,
    )
    seedIdentity = _BuildSeedIdentity()

    identity = product_understanding.ProductUnderstandingComponent._MaybeEnrichIdentityWithLlm(
        seedIdentity,
        productName="주꾸미 볶음",
        distilledIdentity=_BuildDistilledIdentity(),
        encyclopediaEvidence=EncyclopediaEvidenceSet(
            encyclopediaEvidenceId="ency_001",
            productId="prod_001",
            query="주꾸미 볶음",
            configured=True,
        ),
    )

    assert FakeIdentityHintAgent.calls == 0
    assert identity is seedIdentity
