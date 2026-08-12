from __future__ import annotations

import pytest

from bussiness_logic.classification.rules.axis_field_binding import (
    CompilerFieldBindings,
    ResolveAxisFieldBinding,
)
from bussiness_logic.classification.rules import species_taxonomy
from bussiness_logic.classification.rules.branch_decision_evaluator import (
    EvaluateCodeDecision,
)


@pytest.fixture(autouse=True)
def _species_taxonomy(monkeypatch):
    taxonomy = species_taxonomy.ExactSpeciesTaxonomy(
        {
            "exact_concepts": [
                {
                    "id": "crustacean",
                    "labels": ["crustacean"],
                    "parents": [],
                },
                {
                    "id": "shrimp",
                    "labels": ["shrimp"],
                    "parents": ["crustacean"],
                },
                {
                    "id": "fish",
                    "labels": ["fish"],
                    "parents": [],
                },
            ]
        }
    )
    monkeypatch.setattr(
        species_taxonomy,
        "GetExactSpeciesTaxonomy",
        lambda: taxonomy,
    )


def _decision(
    condition: dict[str, str],
    facts: dict,
) -> tuple[str, list[dict[str, str]]]:
    return EvaluateCodeDecision(
        [condition],
        facts,
        frozenset(),
        [],
        lambda *_: {},
        canonical_closed_world=True,
    )


def test_product_identity_cannot_be_answered_by_ntd_or_composition() -> None:
    facts = {
        "identity_hints": {
            "commercial_identity": "stuffed dumpling",
            "food_form": "dumpling",
            "identity_terms": ["filled dough parcel"],
            "normalized_tariff_description": "fish cake with cereal flour",
        },
        "composition_facts": {
            "principal_ingredient": "fish",
            "ingredient_classes": ["fish", "cereal"],
        },
    }

    binding = ResolveAxisFieldBinding("product_identity", facts)

    assert binding.status == "answered"
    assert binding.sourceLane == "identity_hints"
    assert "dumpling" in binding.tokens
    assert "fish" not in binding.tokens
    assert "normalized_tariff_description" not in binding.dtoField
    assert "composition_facts" not in binding.dtoField


def test_species_uses_composition_before_conflicting_identity_hint() -> None:
    facts = {
        "identity_hints": {
            "principal_ingredient_guess": "fish",
            "ingredient_class": "fish",
        },
        "composition_facts": {
            "principal_ingredient": "shrimp",
            "ingredient_classes": ["crustacean"],
            "ingredient_entries": [
                {"ingredient_name": "shrimp", "order_index": 1}
            ],
        },
    }

    binding = ResolveAxisFieldBinding("species_source", facts)

    assert binding.sourceLane == "composition_facts"
    assert "shrimp" in binding.tokens
    assert "fish" not in binding.tokens
    assert binding.tierIndex == 0


def test_species_falls_back_to_identity_when_composition_is_empty() -> None:
    facts = {
        "identity_hints": {
            "principal_ingredient_guess": "cod",
            "ingredient_class": "fish",
        },
        "composition_facts": {
            "principal_ingredient": "",
            "ingredient_classes": [],
            "ingredient_entries": [],
        },
    }

    binding = ResolveAxisFieldBinding("species_source", facts)

    assert binding.sourceLane == "identity_hints"
    assert {"cod", "fish"} <= set(binding.tokens)
    assert binding.tierIndex == 1


def test_composition_state_sentinel_falls_through_to_identity() -> None:
    facts = {
        "identity_hints": {"preservation_state": "frozen"},
        "composition_facts": {"preservation_state": "unknown"},
    }

    binding = ResolveAxisFieldBinding("preservation_state", facts)

    assert binding.sourceLane == "identity_hints"
    assert binding.tokens == frozenset({"frozen"})


def test_composition_state_has_priority_when_present() -> None:
    facts = {
        "identity_hints": {"preservation_state": "frozen"},
        "composition_facts": {"preservation_state": "chilled"},
    }

    binding = ResolveAxisFieldBinding("preservation_state", facts)

    assert binding.sourceLane == "composition_facts"
    assert binding.tokens == frozenset({"chilled"})


def test_relevant_false_boolean_is_answered_negative_evidence() -> None:
    facts = {
        "identity_hints": {
            "physical_form": "whole",
            "food_form": "pasta",
        },
        "composition_facts": {
            "physical_form": "",
            "contains_wrapper_or_dough": False,
        },
    }

    binding = ResolveAxisFieldBinding(
        "physical_form",
        facts,
        questionTokens={"stuffed"},
    )

    assert binding.status == "answered"
    assert binding.canonicalFact == "physical_form_boolean"
    assert binding.tokens == frozenset()
    assert "stuffed" in binding.deniedTokens


def test_irrelevant_boolean_does_not_hide_physical_form() -> None:
    facts = {
        "identity_hints": {
            "physical_form": "minced",
            "food_form": "fish meat",
        },
        "composition_facts": {
            "physical_form": "",
            "contains_wrapper_or_dough": False,
        },
    }

    binding = ResolveAxisFieldBinding(
        "physical_form",
        facts,
        questionTokens={"minced"},
    )

    assert binding.sourceLane == "identity_hints"
    assert "minced" in binding.tokens


def test_quantitative_axis_only_binds_percentages() -> None:
    facts = {
        "identity_hints": {
            "normalized_tariff_description": "containing 20 percent sugar"
        },
        "composition_facts": {
            "ingredient_percentages": [
                {"ingredient_name": "sugar", "percentage": 20}
            ]
        },
    }

    binding = ResolveAxisFieldBinding("quantitative_threshold", facts)

    assert binding.status == "answered"
    assert binding.paths == ("composition_facts.ingredient_percentages",)
    assert "normalized_tariff_description" not in binding.dtoField


def test_axis_without_typed_fact_is_explicitly_unsupported() -> None:
    binding = ResolveAxisFieldBinding(
        "technical_specification",
        {"identity_hints": {"normalized_tariff_description": "electric motor"}},
    )

    assert binding.status == "unsupported"
    assert binding.paths == ()


def test_offline_compiler_uses_same_registry_without_broad_pool() -> None:
    bindings = CompilerFieldBindings()

    assert bindings["product_identity"].startswith(
        "identity_hints.commercial_identity"
    )
    assert "composition_facts.ingredient_percentages" == (
        bindings["quantitative_threshold"]
    )
    assert "residual_other" in bindings
    assert bindings["residual_other"] == ""
    assert "*tokens*" not in set(bindings.values())


def test_runtime_product_identity_ignores_composition_hit() -> None:
    facts = {
        "identity_hints": {
            "commercial_identity": "dumpling",
            "food_form": "dumpling",
            "identity_terms": ["filled dough parcel"],
        },
        "composition_facts": {"principal_ingredient": "fish"},
    }
    status, detail = _decision(
        {
            "cond_type": "product_identity",
            "op": "has_token",
            "value": '["fish"]',
        },
        facts,
    )

    assert status == "violated"
    assert detail[0]["binding_lane"] == "identity_hints"
    assert "composition_facts" not in detail[0]["binding_paths"]


def test_runtime_species_uses_composition_binding_and_traces_it() -> None:
    facts = {
        "identity_hints": {
            "principal_ingredient_guess": "fish",
            "ingredient_class": "fish",
        },
        "composition_facts": {
            "principal_ingredient": "shrimp",
            "ingredient_classes": ["crustacean"],
        },
    }
    status, detail = _decision(
        {
            "cond_type": "species_source",
            "op": "has_token",
            "value": '["shrimp"]',
        },
        facts,
    )

    assert status == "confirmed"
    assert detail[0]["binding_lane"] == "composition_facts"
    assert "principal_ingredient" in detail[0]["binding_paths"]


def test_runtime_unsupported_axis_is_silence_not_ntd_match() -> None:
    facts = {
        "identity_hints": {
            "normalized_tariff_description": "electric motor"
        }
    }
    status, detail = _decision(
        {
            "cond_type": "technical_specification",
            "op": "has_token",
            "value": '["motor"]',
        },
        facts,
    )

    assert status == "undecided"
    assert detail[0]["verdict"] == "undecided"
    assert detail[0]["why"] == "field_empty"
    assert detail[0]["binding_status"] == "unsupported"


def test_runtime_exclusion_uses_canonical_binding_not_global_pool() -> None:
    facts = {
        "identity_hints": {
            "commercial_identity": "fish dumpling",
            "food_form": "dumpling",
            "identity_terms": ["filled fish dumpling"],
        },
        "composition_facts": {"principal_ingredient": "fish"},
    }
    status, detail = _decision(
        {
            "cond_type": "exclusion_boundary",
            "op": "not_contains",
            "value": '["fish"]',
        },
        facts,
    )

    assert status == "violated"
    assert detail[0]["binding_fact"] == "exclusion_fact"
