import assert from "node:assert/strict";
import test from "node:test";
import {
  BuildDocumentPackageOptions,
  CompletedPipelineStage,
  GetPipelineStageState,
  NormalizeStageState,
  NormalizeTariffCode,
  ResolveDocumentPackageSelection,
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

test("분류 단계는 최신 이벤트를 후보 fallback보다 우선한다", () => {
  const emptyViewModel = { candidates: [] };
  const candidateViewModel = { candidates: [{ cn8: "19023010" }] };
  const StageState = (events, viewModel = candidateViewModel) => (
    GetPipelineStageState({ events }, viewModel, "classification")
  );

  assert.equal(StageState([], emptyViewModel), "idle");
  assert.equal(StageState([]), "done");
  assert.equal(StageState([{ stage: "Classification_Component", status: "running" }]), "running");
  assert.equal(StageState([{ stage: "Classification_Component", status: "needs-review" }]), "needs-review");
  assert.equal(StageState([
    { stage: "Classification_Component", status: "needs-review" },
    { stage: "Classification_Component", status: "done" },
  ]), "done");
  assert.equal(StageState([{ stage: "Classification_Component", status: "failed" }]), "failed");
  assert.equal(StageState([{ stage: "Classification_Component", status: "needs_review" }]), "needs-review");
  assert.equal(StageState([{ stage: "Classification_Component", status: "review_required" }]), "needs-review");
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

test("needs-review 파이프라인 상태와 alias를 정규화한다", () => {
  assert.equal(NormalizeStageState("needs-review"), "needs-review");
  assert.equal(NormalizeStageState("needs_review"), "needs-review");
  assert.equal(NormalizeStageState("review_required"), "needs-review");
  assert.equal(NormalizeStageState("unexpected"), "idle");
  assert.equal(NormalizeStageState(null), "idle");
  assert.equal(NormalizeStageState(undefined), "idle");
  assert.equal(
    GetPipelineStageState(
      { events: [{ stage: "Document_Component", status: "review_required" }] },
      { candidates: [] },
      "document_recommendation",
    ),
    "needs-review",
  );
});

test("관세 코드는 구분 기호를 제거해 비교한다", () => {
  assert.equal(NormalizeTariffCode("1605 55-00 00"), "1605550000");
});

test("문서 패키지는 TARIC10, CN8, HS6 순으로 후보와 연결한다", () => {
  const packages = {
    "1605550000": [{ taric10: "1605 55 00 00" }],
    "1605550090": [{ cn8: "16055500" }],
    "1605590000": [{ hs6: "160555" }],
    "2106900000": [{ taric10: "2106900000" }],
  };
  const options = BuildDocumentPackageOptions(packages, {
    hs6: "160555",
    cn8: "16055500",
    taric10: "1605550000",
  });

  assert.deepEqual(options.map((option) => option.matchLevel), [
    "taric10",
    "none",
    "none",
    "none",
  ]);
  assert.equal(options.length, 4);
  assert.deepEqual(ResolveDocumentPackageSelection(options), {
    taric: "1605550000",
    manual: false,
  });
});

test("TARIC10이 없으면 CN8, 이어서 HS6 패키지를 기본 선택한다", () => {
  const cn8Options = BuildDocumentPackageOptions(
    { "1605550090": [{ cn8: "16055500" }] },
    { cn8: "16055500", hs6: "160555" },
  );
  const hs6Options = BuildDocumentPackageOptions(
    { "1605559090": [{ hs6: "160555" }] },
    { hs6: "160555" },
  );

  assert.equal(ResolveDocumentPackageSelection(cn8Options).taric, "1605550090");
  assert.equal(ResolveDocumentPackageSelection(hs6Options).taric, "1605559090");
});

test("직접 매칭이 없으면 임의 패키지를 선택하지 않는다", () => {
  const options = BuildDocumentPackageOptions(
    { "2106900000": [{ taric10: "2106900000" }] },
    { taric10: "1605550000" },
  );
  assert.deepEqual(ResolveDocumentPackageSelection(options), { taric: "", manual: false });
});

test("사용자의 문서 패키지 수동 선택은 후보 변경 후에도 보존한다", () => {
  const options = BuildDocumentPackageOptions(
    {
      "1605550000": [{ taric10: "1605550000" }],
      "2106900000": [{ taric10: "2106900000" }],
    },
    { taric10: "1605550000" },
  );
  assert.deepEqual(
    ResolveDocumentPackageSelection(options, { taric: "2106900000", manual: true }),
    { taric: "2106900000", manual: true },
  );
});

test("수동 선택 전에는 후보 변경에 맞춰 기본 패키지를 다시 선택한다", () => {
  const first = BuildDocumentPackageOptions(
    { "1605550000": [{}], "2106900000": [{}] },
    { taric10: "1605550000" },
  );
  const second = BuildDocumentPackageOptions(
    { "1605550000": [{}], "2106900000": [{}] },
    { taric10: "2106900000" },
  );
  assert.equal(ResolveDocumentPackageSelection(first).taric, "1605550000");
  assert.equal(ResolveDocumentPackageSelection(second).taric, "2106900000");
});
