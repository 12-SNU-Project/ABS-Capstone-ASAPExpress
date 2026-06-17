"""Classification page interaction callbacks."""

from __future__ import annotations

from typing import Any

from dash import ALL, Dash, Input, Output, State, ctx, no_update

from frontend.ui import classification_dash


def RegisterClassificationCallbacks(app: Dash) -> None:
    app.callback(
        Output("input-detail-drawer-store", "data"),
        Input({"type": "pipeline-step-card", "step": ALL}, "n_clicks"),
        Input({"type": "input-detail-drawer-close", "target": ALL}, "n_clicks"),
        State("store-result", "data"),
        prevent_initial_call=True,
    )(_toggle_input_detail_drawer)

    app.callback(
        Output("candidate-tree-drawer-store", "data"),
        Input({"type": "pipeline-step-card", "step": ALL}, "n_clicks"),
        Input({"type": "candidate-tree-drawer-close", "target": ALL}, "n_clicks"),
        State("store-result", "data"),
        prevent_initial_call=True,
    )(_toggle_candidate_tree_drawer)

    app.callback(
        Output("classification-result-drawer-store", "data"),
        Input({"type": "pipeline-step-card", "step": ALL}, "n_clicks"),
        Input({"type": "classification-result-drawer-close", "target": ALL}, "n_clicks"),
        State("store-result", "data"),
        prevent_initial_call=True,
    )(_toggle_classification_result_drawer)


def _toggle_input_detail_drawer(
    _stepClicks: list[int | None],
    _closeClicks: list[int | None],
    resultData: dict[str, Any] | None,
) -> bool | Any:
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "input-detail-drawer-close":
        return False
    if not isinstance(resultData, dict):
        return no_update
    inputView = resultData.get("input_processing_view")
    if not isinstance(inputView, dict) or not inputView:
        return no_update
    if isinstance(triggered, dict) and triggered.get("type") == "pipeline-step-card":
        step = triggered.get("step")
        stepStates = classification_dash.pipeline_step_statuses(resultData)
        if step in {"collect", "reconstruct"} and stepStates.get(step, {}).get("status") == "completed":
            return True
    return no_update


def _toggle_candidate_tree_drawer(
    _stepClicks: list[int | None],
    _closeClicks: list[int | None],
    resultData: dict[str, Any] | None,
) -> bool | Any:
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "candidate-tree-drawer-close":
        return False
    if not isinstance(resultData, dict):
        return no_update
    candidateSet = resultData.get("candidate_code_set") or {}
    candidates = candidateSet.get("candidates") if isinstance(candidateSet, dict) else []
    if not isinstance(candidates, list) or not candidates:
        return no_update
    if isinstance(triggered, dict) and triggered.get("type") == "pipeline-step-card":
        step = triggered.get("step")
        stepStates = classification_dash.pipeline_step_statuses(resultData)
        if step == "candidate" and stepStates.get(step, {}).get("status") == "completed":
            return True
    return no_update


def _toggle_classification_result_drawer(
    _stepClicks: list[int | None],
    _closeClicks: list[int | None],
    resultData: dict[str, Any] | None,
) -> bool | Any:
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "classification-result-drawer-close":
        return False
    if not isinstance(resultData, dict):
        return no_update
    candidateSet = resultData.get("candidate_code_set") or {}
    candidates = candidateSet.get("candidates") if isinstance(candidateSet, dict) else []
    if not isinstance(candidates, list) or not candidates:
        return no_update
    if isinstance(triggered, dict) and triggered.get("type") == "pipeline-step-card":
        step = triggered.get("step")
        stepStates = classification_dash.pipeline_step_statuses(resultData)
        if step == "validation" and stepStates.get(step, {}).get("status") == "completed":
            return True
    return no_update
