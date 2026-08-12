from __future__ import annotations

import pytest

from bussiness_logic.classification.rules.branch_predicate_evaluator import (
    EvaluatePredicates,
)


DTO_FIELD = (
    "identity_hints.food_form;"
    "identity_hints.product_form_terms;"
    "composition_facts.contains_wrapper_or_dough"
)
PREDICATE = {
    "axis": "form",
    "dto_field": DTO_FIELD,
    "op": "has_token",
    "value": '["stuffed"]',
}


def _evaluate(
    *,
    food_form: str = "",
    form_terms: list[str] | None = None,
    wrapper: bool | None = None,
) -> tuple[float, dict[str, str]]:
    composition: dict[str, object] = {}
    if wrapper is not None:
        composition["contains_wrapper_or_dough"] = wrapper
    facts = {
        "identity_hints": {
            "food_form": food_form,
            "product_form_terms": list(form_terms or []),
        },
        "composition_facts": composition,
    }
    delta, verdicts = EvaluatePredicates(
        [PREDICATE],
        frozenset({"stuffed"}),
        facts,
        closed_world=True,
        allow_pool=False,
    )
    return delta, verdicts[0]


@pytest.mark.parametrize("term", ["stuffed pasta", "filled pasta"])
def test_affirmative_form_is_true(term: str) -> None:
    delta, result = _evaluate(form_terms=[term])

    assert delta == 3.0
    assert result["verdict"] == "true"
    assert result["why"] == "affirmative_source_text"


@pytest.mark.parametrize("term", ["not stuffed", "non-stuffed"])
def test_explicit_negative_form_is_false(term: str) -> None:
    delta, result = _evaluate(form_terms=[term], wrapper=False)

    assert delta == -100.0
    assert result["verdict"] == "false"
    assert result["why"] == "explicit_negation"
    assert result["authority"] == "signed_polarity"


def test_neutral_legal_qualifier_is_silent() -> None:
    delta, result = _evaluate(
        form_terms=["whether or not cooked or stuffed"]
    )

    assert delta == 0.0
    assert result["verdict"] == "unknown"
    assert result["why"] == "neutral_scope_qualifier"
    assert result["authority"] == "signed_polarity"


def test_wrapper_true_requires_affirmative_text() -> None:
    delta, result = _evaluate(food_form="pasta", wrapper=True)

    assert delta == 0.0
    assert result["verdict"] == "unknown"
    assert result["why"] == "wrapper_requires_text_corroboration"


def test_wrapper_true_with_corroboration_is_true() -> None:
    delta, result = _evaluate(
        food_form="dumpling",
        form_terms=["filled wheat dough parcel"],
        wrapper=True,
    )

    assert delta == 3.0
    assert result["verdict"] == "true"


def test_wrapper_false_requires_negative_text() -> None:
    delta, result = _evaluate(food_form="pasta", wrapper=False)

    assert delta == 0.0
    assert result["verdict"] == "unknown"
    assert result["why"] == "wrapper_requires_text_corroboration"


def test_conflicting_text_is_silent() -> None:
    delta, result = _evaluate(
        form_terms=["stuffed pasta", "not stuffed"],
        wrapper=True,
    )

    assert delta == 0.0
    assert result["verdict"] == "unknown"
    assert result["why"] == "polarity_conflict"


def test_dumpling_oracle_shape_stays_confirmed() -> None:
    delta, result = _evaluate(
        food_form="stuffed dumpling",
        form_terms=["stuffed", "filled", "fried"],
        wrapper=True,
    )

    assert delta == 3.0
    assert result["verdict"] == "true"
