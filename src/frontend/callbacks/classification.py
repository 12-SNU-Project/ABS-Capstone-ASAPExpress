"""Classification page interaction callbacks."""

from __future__ import annotations

from dash import ALL, Dash, Input, Output, State, ctx, no_update

from bussiness_logic.utils.json_types import JsonObject
from frontend.ui import classification_dash


def RegisterClassificationCallbacks(app: Dash) -> None:
    app.callback(
        Output("input-detail-drawer-store", "data"),
        Output("candidate-tree-drawer-store", "data"),
        Output("classification-result-drawer-store", "data"),
        Input({"type": "pipeline-step-card", "step": ALL}, "n_clicks"),
        Input({"type": "taric-branch-package-row", "candidate": ALL, "taric10": ALL}, "n_clicks"),
        Input({"type": "input-detail-drawer-close", "target": ALL}, "n_clicks"),
        Input({"type": "candidate-tree-drawer-close", "target": ALL}, "n_clicks"),
        Input({"type": "classification-result-drawer-close", "target": ALL}, "n_clicks"),
        State("store-result", "data"),
        prevent_initial_call=True,
    )(_update_classification_drawers)


def _update_classification_drawers(
    _stepClicks: list[int | None],
    _taricBranchClicks: list[int | None],
    _inputCloseClicks: list[int | None],
    _candidateCloseClicks: list[int | None],
    _classificationCloseClicks: list[int | None],
    resultData: JsonObject | None,
) -> tuple[object, object, object]:
    if _triggered_click_count() <= 0:
        return (no_update, no_update, no_update)
    return _resolve_classification_drawer_state(ctx.triggered_id, resultData)


def _triggered_click_count() -> int:
    if not ctx.triggered:
        return 0
    try:
        return int(ctx.triggered[0].get("value") or 0)
    except (TypeError, ValueError):
        return 0


def _resolve_classification_drawer_state(
    triggered: object,
    resultData: JsonObject | None,
) -> tuple[object, object, object]:
    closedState = (False, False, False)
    if isinstance(triggered, dict) and triggered.get("type") in {
        "input-detail-drawer-close",
        "candidate-tree-drawer-close",
        "classification-result-drawer-close",
    }:
        return closedState
    if not isinstance(resultData, dict):
        return (no_update, no_update, no_update)
    if isinstance(triggered, dict) and triggered.get("type") == "taric-branch-package-row":
        return (
            False,
            False,
            {
                "candidate": triggered.get("candidate") or True,
                "taric10": triggered.get("taric10"),
            },
        )
    if not isinstance(triggered, dict) or triggered.get("type") != "pipeline-step-card":
        return (no_update, no_update, no_update)

    step = triggered.get("step")
    stepStates = classification_dash.pipeline_step_statuses(resultData)
    if stepStates.get(step, {}).get("status") not in {"completed", "warning", "failed"}:
        return (no_update, no_update, no_update)

    if step in {"collect", "reconstruct"}:
        inputView = resultData.get("input_processing_view")
        if not isinstance(inputView, dict) or not inputView:
            return (no_update, no_update, no_update)
        mode = "raw" if step == "collect" else "reconstructed"
        return (mode, False, False)

    if step == "candidate":
        if not classification_dash.has_candidate_scope_tree(resultData):
            return (no_update, no_update, no_update)
        return (False, True, False)

    if step != "validation":
        return (no_update, no_update, no_update)

    candidateSet = resultData.get("candidate_code_set") or {}
    candidates = candidateSet.get("candidates") if isinstance(candidateSet, dict) else []
    hasCandidates = isinstance(candidates, list) and bool(candidates)
    hasClassificationStatus = (
        isinstance(candidateSet, dict)
        and bool(candidateSet.get("classification_status"))
    )
    if not hasCandidates and not hasClassificationStatus:
        return (no_update, no_update, no_update)
    return (False, False, True)
