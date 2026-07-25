from pathlib import Path

from backend.pipeline_service import PipelineRunService, RunRegistry
from bussiness_logic.pipeline.blackboard.store import BlackboardStore
from bussiness_logic.pipeline.component_base import ComponentResult


def test_answer_replay_persists_auditable_fact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_001"
    store = BlackboardStore.create(
        run_id="run_001",
        run_dir=run_dir,
        runs_dir=tmp_path,
        validate_on_write=False,
    )
    blackboard = store.load()
    blackboard["user_questions"] = [{
        "object_type": "UserQuestion",
        "created_by": "Classification_Component",
        "created_at": "2026-07-24T00:00:00+09:00",
        "user_question_id": "uq_001",
        "question_key": "cq_example",
        "question_text": "제품에 달걀이 포함되어 있습니까?",
        "asked_by": "Classification_Component",
        "stage": "hs6",
        "parent_code": "1902",
        "candidate_code": "190211",
        "axis": "material_composition",
        "canonical_field": "composition_facts.ingredient_classes",
        "condition_value": '["egg"]',
        "context_scope": "",
        "bti_evidence": [],
        "required_for": ["stage:hs6", "candidate:190211"],
        "options": ["yes", "no", "unknown"],
        "answer": None,
        "answered_at": None,
        "active": True,
        "resolved_at": None,
    }]
    blackboard["classification_answer_facts"] = []
    store.save(blackboard)

    def fake_execute(_component, replay_store):
        replay_blackboard = replay_store.load()
        assert replay_blackboard["classification_answer_facts"][-1]["answer"] == "yes"
        replay_blackboard.setdefault("candidate_code_sets", []).append({
            "candidate_set_id": "ccs_001",
            "candidates": [{"cn8": "19021100"}],
        })
        replay_store.save(replay_blackboard)
        return ComponentResult(success=True, component_run_id="cr_001")

    from bussiness_logic.classification.components.classification import (
        ClassificationComponent,
    )

    monkeypatch.setattr(ClassificationComponent, "Execute", fake_execute)

    registry = RunRegistry()
    registry.CreateRun(
        "job_test",
        query="dumpling",
        facts={},
        status="completed",
    )
    service = PipelineRunService(registry, lambda **_kwargs: {})
    snapshot = service.ReclassifyWithQuestionAnswers(
        "job_test",
        run_dir,
        [{"user_question_id": "uq_001", "answer": "yes"}],
    )

    replayed = store.load()
    question = replayed["user_questions"][0]
    answer_fact = replayed["classification_answer_facts"][0]
    assert question["answer"] == "yes"
    assert question["answer_id"] == answer_fact["answer_id"]
    assert answer_fact["question_key"] == "cq_example"
    assert answer_fact["source"] == "user"
    assert snapshot["candidate_code_set"]["candidates"][0]["cn8"] == "19021100"
