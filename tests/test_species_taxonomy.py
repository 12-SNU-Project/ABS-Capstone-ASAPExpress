import pytest

from bussiness_logic.classification.rules import species_taxonomy
from bussiness_logic.classification.rules.species_taxonomy import (
    EvaluateSpeciesQuestion,
    ExpandExactTaxonomy,
)


@pytest.fixture(autouse=True)
def _taxonomy(monkeypatch):
    payload = {
        "exact_concepts": [
            {
                "id": "aquatic_invertebrate",
                "labels": ["aquatic invertebrate"],
                "parents": [],
            },
            {
                "id": "mollusc",
                "labels": ["mollusc", "molluscs"],
                "parents": ["aquatic_invertebrate"],
            },
            {
                "id": "cephalopod",
                "labels": ["cephalopod"],
                "parents": ["mollusc"],
            },
            {
                "id": "crustacean",
                "labels": ["crustacean", "crustaceans"],
                "parents": ["aquatic_invertebrate"],
            },
            {
                "id": "octopus",
                "labels": ["octopus"],
                "parents": ["cephalopod"],
            },
            {
                "id": "shrimp",
                "labels": ["shrimp", "white-leg shrimp"],
                "parents": ["crustacean"],
            },
            {"id": "fish", "labels": ["fish"], "parents": []},
            {"id": "cod", "labels": ["cod"], "parents": ["fish"]},
            {"id": "pollack", "labels": ["pollack"], "parents": ["fish"]},
        ]
    }
    taxonomy = species_taxonomy.ExactSpeciesTaxonomy(payload)
    monkeypatch.setattr(
        species_taxonomy,
        "GetExactSpeciesTaxonomy",
        lambda: taxonomy,
    )


def _facts(value):
    return {
        "composition_facts": {
            "principal_ingredient": value,
        },
    }


def _evaluate(question, fact):
    return EvaluateSpeciesQuestion(
        [question],
        _facts(fact),
        ["composition_facts.principal_ingredient"],
    )


def test_exact_species_expands_upward_only():
    expanded = set(ExpandExactTaxonomy(["octopus"]))
    assert "octopus" in expanded
    assert "cephalopod" in expanded
    assert "mollusc" in expanded
    assert "aquatic invertebrate" in expanded
    assert "shrimp" not in expanded


def test_descendant_fact_satisfies_class_question():
    result = _evaluate("crustaceans", "white-leg shrimp")
    assert result.verdict == "O"
    assert result.reason == "fact_is_question_or_descendant"


def test_broad_fact_does_not_infer_exact_species():
    result = _evaluate("shrimp", "crustacean")
    assert result.verdict == "SILENCE"
    assert result.reason == "fact_is_only_question_ancestor"


def test_disjoint_exact_species_is_false():
    result = _evaluate("shrimp", "cod")
    assert result.verdict == "X"
    assert result.reason == "authoritative_taxa_disjoint"


def test_related_fish_species_are_not_synonyms():
    assert _evaluate("cod", "pollack").verdict == "X"


def test_unknown_taxon_is_silence_not_false():
    assert _evaluate("langoustine", "unknown seafood").verdict == "SILENCE"


def test_token_boundaries_prevent_substring_match():
    assert _evaluate("cod", "decode product").verdict == "SILENCE"
