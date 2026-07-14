from bussiness_logic.pipeline.model.pipeline_dto import (
    EncyclopediaEntryDto,
    EncyclopediaEvidenceSet,
)
from bussiness_logic.product.services.identity_distiller import IdentityDistillerService


def test_identity_distiller_uses_wikipedia_evidence_only() -> None:
    evidence = EncyclopediaEvidenceSet(
        encyclopediaEvidenceId="ency_001",
        productId="prod_001",
        query="octopus",
        configured=True,
        entries=(
            EncyclopediaEntryDto(
                title="Octopus",
                description=(
                    "Octopus is often prepared as cooked seafood, dried, "
                    "or seasoned in processed dishes."
                ),
                link="https://en.wikipedia.org/wiki/Octopus",
                contentHash="hash001",
            ),
        ),
        qualityStatus="raw_entries",
    )

    facts = IdentityDistillerService().BuildFacts(
        distilledIdentityId="distid_001",
        productId="prod_001",
        encyclopediaEvidence=evidence,
    )

    assert facts.sourceEncyclopediaEvidenceId == "ency_001"
    assert facts.commercialIdentity == "Octopus"
    assert facts.sourceDescriptions == (evidence.entries[0].description,)
    assert "cooked" in facts.processingSignalTerms
    assert "processed" in facts.processingSignalTerms
    assert facts.productId == "prod_001"
