import assert from "node:assert/strict";
import test from "node:test";
import {
  CompletedPipelineStage,
  GetPipelineStageState,
} from "./classificationViewModel.js";

test("실행 이벤트와 결과 DTO를 파이프라인 표시 상태로 변환한다", () => {
  const emptyViewModel = { candidates: [] };
  assert.equal(
    GetPipelineStageState(
      { events: [{ stage: "HS2_Routing_Component", status: "running" }] },
      emptyViewModel,
      "classification",
    ),
    "running",
  );
  assert.equal(
    GetPipelineStageState({}, { candidates: [{ cn8: "19023010" }] }, "classification"),
    "done",
  );
  assert.equal(
    GetPipelineStageState({ document_packages: [{ taric10: "1902301010" }] }, emptyViewModel, "document_recommendation"),
    "done",
  );
});

test("입력 복원 완료 결과는 상품 정보 수집 단계에 머문다", () => {
  assert.equal(
    CompletedPipelineStage({
      job_id: "reconstruct_123",
      events: [{ stage: "Input_Reconstruction", status: "completed" }],
    }),
    "product_collection",
  );
  assert.equal(CompletedPipelineStage({ job_id: "job_123" }), "classification");
});
