from __future__ import annotations

import pytest

from bussiness_logic.classification.services import axis_verdict


@pytest.fixture(autouse=True)
def _hs6_axis_map(monkeypatch):
    monkeypatch.setattr(
        axis_verdict,
        "_sub_axmap_cache",
        [{"190220": {"axis": "processing_method"}}],
    )


def _facts() -> dict:
    return {
        "identity_hints": {
            "processing_state": "prepared",
            "food_form": "pasta",
        },
        "composition_facts": {
            "processing_state": "frozen cooked prepared",
            "contains_wrapper_or_dough": False,
        },
    }


def _row(verdict: str) -> dict:
    return {
        "code": "190220",
        "descr": "Stuffed pasta, whether or not cooked or otherwise prepared",
        "decision": "undecided",
        "decision_detail": [],
        "predicate_results": [{
            "axis": "form",
            "op": "has_token",
            "value": "stuffed",
            "verdict": verdict,
            "why": "test_signed_fact",
            "authority": "signed_polarity",
            "decisive": "true",
        }],
    }


def test_signed_unknown_blocks_broad_processing_confirmation() -> None:
    row = _row("unknown")

    axis_verdict.StampHs6AxisVerdicts([row], _facts())

    assert row["decision"] == "undecided"
    assert row["decision_detail"][-1]["verdict"] == "silent"
    assert row["decision_detail"][-1]["why"].endswith(
        "signed_polarity_unresolved"
    )


def test_signed_false_excludes_even_when_processing_state_matches() -> None:
    row = _row("false")

    axis_verdict.StampHs6AxisVerdicts([row], _facts())

    assert row["decision"] == "violated"
    assert row["decision_detail"][-1]["verdict"] == "false"
    assert row["decision_detail"][-1]["why"].endswith(
        "signed_polarity_false"
    )


def test_signed_true_confirms_without_reducing_to_processing_state() -> None:
    row = _row("true")

    axis_verdict.StampHs6AxisVerdicts([row], _facts())

    assert row["decision"] == "confirmed"
    assert row["decision_detail"][-1]["verdict"] == "true"
    assert row["decision_detail"][-1]["why"].endswith(
        "signed_polarity_true"
    )


def test_unsigned_row_keeps_axis_fallback_behavior() -> None:
    row = _row("unknown")
    row["predicate_results"][0].pop("authority")

    axis_verdict.StampHs6AxisVerdicts([row], _facts())

    assert row["decision"] == "confirmed"
    assert row["decision_detail"][-1]["why"] == "hs6_axis_map"
