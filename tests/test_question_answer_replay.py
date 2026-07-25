import json
from pathlib import Path

import pytest

from backend.pipeline_service import PipelineRunRequest, PipelineRunService, RunRegistry
from bussiness_logic.pipeline.pipeline_manager import ExportPipelineManager
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
        "contract_version": 2,
        "question_key": "cq_example",
        "question_text": "제품에 달걀이 포함되어 있습니까?",
        "asked_by": "Classification_Component",
        "stage": "hs6",
        "parent_code": "1902",
        "candidate_code": "190211",
        "axis": "material_composition",
        "predicate_op": "contains",
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
        answerFact = replay_blackboard["classification_answer_facts"][-1]
        candidateSet = {
            "candidate_set_id": "ccs_001",
            "classification_status": (
                "needs_more_facts"
                if answerFact["answer"] == "unknown"
                else "resolved"
            ),
            "candidates": (
                []
                if answerFact["answer"] == "unknown"
                else [{"cn8": "19021100"}]
            ),
        }
        if answerFact["answer"] == "unknown":
            candidateSet["resolver_debug"] = {
                "unresolved": {
                    "question_options": [{
                        "question_key": answerFact["question_key"],
                    }],
                },
            }
        replay_blackboard.setdefault("candidate_code_sets", []).append(candidateSet)
        replay_store.save(replay_blackboard)
        return ComponentResult(success=True, component_run_id="cr_001")

    from bussiness_logic.classification.components.classification import (
        ClassificationComponent,
    )
    from bussiness_logic.document.pipeline.document_recommendation_pipeline import (
        DocumentRecommendationPipeline,
    )

    monkeypatch.setattr(ClassificationComponent, "Execute", fake_execute)

    documentRuns = []

    def fake_document_run(_pipeline, context):
        documentRuns.append(context.store.run_id)

    monkeypatch.setattr(DocumentRecommendationPipeline, "Run", fake_document_run)

    registry = RunRegistry()
    registry.CreateRun(
        "job_test",
        query="dumpling",
        facts={},
        status="awaiting_input",
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
    assert answer_fact["contract_version"] == 2
    assert answer_fact["predicate_op"] == "contains"
    assert answer_fact["source"] == "user"
    assert snapshot["candidate_code_set"]["candidates"][0]["cn8"] == "19021100"
    assert snapshot["job_status"] == "completed"
    assert documentRuns == ["run_001"]

    repeated = service.ReclassifyWithQuestionAnswers(
        "job_test",
        run_dir,
        [{"user_question_id": "uq_001", "answer": "yes"}],
    )
    assert len(store.load()["classification_answer_facts"]) == 1
    assert repeated["job_status"] == "completed"
    assert documentRuns == ["run_001"]

    blackboard = store.load()
    blackboard["user_questions"].append({
        **blackboard["user_questions"][0],
        "user_question_id": "uq_002",
        "question_key": "cq_unknown",
        "answer": None,
        "answer_id": None,
        "answered_at": None,
        "active": True,
        "resolved_at": None,
    })
    store.save(blackboard)
    registry.UpdateRun("job_test", status="awaiting_input")
    unknown = service.ReclassifyWithQuestionAnswers(
        "job_test",
        run_dir,
        [{"user_question_id": "uq_002", "answer": "unknown"}],
    )
    assert unknown["job_status"] == "awaiting_input"
    assert store.load()["user_questions"][1]["active"] is True
    assert documentRuns == ["run_001"]

    resolved = service.ReclassifyWithQuestionAnswers(
        "job_test",
        run_dir,
        [{"user_question_id": "uq_002", "answer": "no"}],
    )
    assert resolved["job_status"] == "completed"
    assert len(store.load()["classification_answer_facts"]) == 3
    assert documentRuns == ["run_001", "run_001"]

    blackboard = store.load()
    blackboard["user_questions"].append({
        **blackboard["user_questions"][0],
        "user_question_id": "uq_legacy",
        "contract_version": 1,
        "answer": None,
        "active": True,
    })
    store.save(blackboard)
    registry.UpdateRun("job_test", status="awaiting_input")
    with pytest.raises(ValueError, match="contract V2"):
        service.ReclassifyWithQuestionAnswers(
            "job_test",
            run_dir,
            [{"user_question_id": "uq_legacy", "answer": "yes"}],
        )


def test_pipeline_service_pauses_and_emits_run_paused(tmp_path: Path) -> None:
    candidateSet = {
        "candidate_set_id": "ccs_waiting",
        "classification_status": "needs_more_facts",
        "candidates": [],
    }

    def fake_pipeline(**_kwargs):
        return {
            "blackboard": {
                "candidate_code_sets": [candidateSet],
                "user_questions": [{
                    "user_question_id": "uq_waiting",
                    "question_text": "질문",
                    "active": True,
                }],
                "document_packages": [],
                "component_runs": [],
            },
            "candidate_code_set": candidateSet,
            "run_id": "run_waiting",
            "run_dir": str(tmp_path),
        }

    registry = RunRegistry()
    registry.CreateRun("job_waiting", query="dumpling", facts={})
    PipelineRunService(registry, fake_pipeline).Run(
        "job_waiting",
        request=PipelineRunRequest(query="dumpling"),
    )

    snapshot = registry.BuildUiResult("job_waiting")
    stream = "".join(registry.StreamEvents("job_waiting"))
    assert snapshot["job_status"] == "awaiting_input"
    assert "event: run_paused" in stream
    assert json.loads((tmp_path / "api_snapshot.json").read_text("utf-8"))[
        "status"
    ] == "awaiting_input"


def test_unresolved_classification_without_question_fails(tmp_path: Path) -> None:
    candidateSet = {
        "candidate_set_id": "ccs_failed",
        "classification_status": "needs_more_facts",
        "failure_reason": "question_generation_failed",
        "candidates": [],
    }
    registry = RunRegistry()
    registry.CreateRun("job_failed", query="dumpling", facts={})
    PipelineRunService(
        registry,
        lambda **_kwargs: {
            "blackboard": {
                "candidate_code_sets": [candidateSet],
                "user_questions": [],
                "document_packages": [],
            },
            "candidate_code_set": candidateSet,
            "run_id": "run_failed",
            "run_dir": str(tmp_path),
        },
    ).Run("job_failed", PipelineRunRequest(query="dumpling"))

    snapshot = registry.BuildUiResult("job_failed")
    assert snapshot["job_status"] == "failed"
    assert snapshot["error"] == "question_generation_failed"


def test_restored_snapshot_preserves_question_wait_state() -> None:
    candidateSet = {
        "classification_status": "needs_more_facts",
        "candidates": [],
    }
    registry = RunRegistry()
    registry.RestoreRun("job_restored", {
        "query": "dumpling",
        "facts": {},
        "result": {
            "candidate_code_set": candidateSet,
            "user_questions": [{
                "user_question_id": "uq_restored",
                "question_text": "질문",
                "active": True,
            }],
        },
    })
    assert registry.BuildUiResult("job_restored")["job_status"] == "awaiting_input"


def test_export_pipeline_stops_before_document_on_question(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    class ClassificationStep:
        def Run(self, context) -> None:
            calls.append("classification")
            context.store.append("candidate_code_sets", {
                "object_type": "ClassificationCandidateSet",
                "created_by": "Classification_Component",
                "created_at": "2026-07-25T00:00:00+09:00",
                "candidate_set_id": "ccs_waiting",
                "product_id": "product_waiting",
                "classification_status": "needs_more_facts",
                "failure_reason": "question_required_at_hs6",
                "shortlisted_candidates": [],
                "candidates": [],
            })
            context.store.append("user_questions", {
                "object_type": "UserQuestion",
                "created_by": "Classification_Component",
                "created_at": "2026-07-25T00:00:00+09:00",
                "user_question_id": "uq_waiting",
                "question_text": "분류 질문",
                "asked_by": "Classification_Component",
                "active": True,
                "required_for": ["stage:hs6"],
                "options": ["yes", "no"],
                "answer": None,
                "answered_at": None,
            })

    class DocumentStep:
        def Run(self, _context) -> None:
            calls.append("document")

    manager = ExportPipelineManager(pipelineOutputsRoot=tmp_path)
    monkeypatch.setattr(
        manager,
        "_BuildSteps",
        lambda: [ClassificationStep(), DocumentStep()],
    )
    result = manager.Run(query="dumpling", facts={}, job_id="job_waiting")
    assert result["candidate_code_set"]["classification_status"] == "needs_more_facts"
    assert calls == ["classification"]
