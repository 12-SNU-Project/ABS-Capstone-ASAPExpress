import assert from "node:assert/strict";
import test from "node:test";
import {
  BuildDocumentPackageViewModel,
  buildPreArrivalModel,
  groupKey,
} from "./documentPackageViewModel.js";

const packageData = {
  checklist_summary: {
    document_binding_cards: [{
      document_id: "commercial_invoice",
      document_name_ko: "상업송장",
      required_level: "mandatory",
      prepared_by_ko: "수출자",
      submitted_to_ko: "수입자",
      source_bindings: [{ source_layer: "baseline" }],
      fields: [{ field_key: "invoice_number", label_ko: "송장 번호" }],
    }],
  },
};

test("문서 패키지 DTO를 기본 통관서류 뷰 모델로 변환한다", () => {
  const model = BuildDocumentPackageViewModel(packageData);
  assert.deepEqual(model.baselineRows, [{
    documentId: "commercial_invoice",
    documentName: "상업송장",
    family: "",
    requiredLevelRaw: "mandatory",
    requiredLevel: "필수",
    preparedBy: "수출자",
    submittedTo: "수입자",
    unresolvedCount: 0,
    fields: ["송장 번호"],
  }]);
});

test("사용자가 적용한 수입요건만 조건부 최종서류에 추가한다", () => {
  const requirement = {
    groupName: "위생증명 검토",
    groupId: "health",
    sourceType: "taric",
    preparationItemRows: [{
      item_type: "document",
      recommendation_mode: "conditional_required_document",
      item_name_ko: "위생증명서",
      item_detail_ko: "공식통제 대상일 때 준비",
    }],
  };
  const baseline = BuildDocumentPackageViewModel(packageData).baselineRows;
  assert.deepEqual(
    buildPreArrivalModel(baseline, [], {}).finalDocuments.map((document) => document.documentName),
    ["상업송장"],
  );
  assert.equal(buildPreArrivalModel(baseline, [requirement], {}).finalDocuments.length, 1);
  assert.deepEqual(
    buildPreArrivalModel(baseline, [requirement], { [groupKey(requirement)]: true })
      .finalDocuments.map((document) => document.documentName),
    ["상업송장", "위생증명서"],
  );
});
