import assert from "node:assert/strict";
import test from "node:test";
import {
  BuildDocumentPackageViewModel,
  buildPreArrivalModel,
  groupKey,
} from "./documentPackageViewModel.js";

const packageData = {
  taric10: "1605550000",
  checklist_summary: {
    document_binding_cards: [{
      document_id: "commercial_invoice",
      document_name_ko: "상업송장",
      required_level: "mandatory",
      prepared_by_ko: "수출자",
      submitted_to_ko: "수입자",
      source_bindings: [{ source_layer: "baseline" }],
      fields: [{ field_key: "invoice_number", label_ko: "송장 번호" }],
      required_evidence: ["거래 계약"],
      regulation_references: ["Regulation (EU) 952/2013"],
      celex_references: ["32013R0952"],
      official_links: ["https://eur-lex.europa.eu/eli/reg/2013/952/oj"],
      verification_notes: ["신고 전 송장 정보 대조"],
    }],
  },
};

test("문서 패키지 DTO를 기본 통관서류 뷰 모델로 변환한다", () => {
  const model = BuildDocumentPackageViewModel(packageData);
  assert.deepEqual(model.baselineRows[0], {
    documentId: "commercial_invoice",
    documentName: "상업송장",
    family: "",
    requiredLevelRaw: "mandatory",
    requiredLevel: "필수",
    preparedBy: "수출자",
    submittedTo: "수입자",
    missingFacts: [],
    unresolvedConditions: [],
    unresolvedCount: 0,
    fields: ["송장 번호"],
    requiredEvidence: ["거래 계약"],
    regulations: ["Regulation (EU) 952/2013"],
    celexReferences: ["32013R0952"],
    officialLinks: ["https://eur-lex.europa.eu/eli/reg/2013/952/oj"],
    verificationNotes: ["신고 전 송장 정보 대조"],
    sourceMetadata: {
      documentCode: "",
      decisionStatus: "",
      sourceBindings: [{ source_layer: "baseline" }],
      preChecks: [],
      postRequirements: [],
      preTaricLinks: [],
      postTaricLinks: [],
      taricCertificates: [],
    },
  });
});

test("TARIC10 최종 추천서류가 기본서류 상세 DTO를 보존한다", () => {
  const viewModel = BuildDocumentPackageViewModel(packageData);
  const finalModel = buildPreArrivalModel(viewModel.baselineRows, [], {});
  const baseline = viewModel.baselineRows[0];
  const recommended = finalModel.finalDocuments[0];

  assert.equal(packageData.taric10, "1605550000");
  assert.equal(viewModel.baselineRows.length, 1);
  assert.equal(finalModel.finalDocuments.length, 1);
  [
    "preparedBy",
    "submittedTo",
    "fields",
    "requiredEvidence",
    "regulations",
    "celexReferences",
    "officialLinks",
    "verificationNotes",
  ].forEach((field) => assert.deepEqual(recommended[field], baseline[field]));
  assert.deepEqual(recommended.sourceMetadata, baseline.sourceMetadata);
  assert.notEqual(recommended.fields, baseline.fields);
  assert.notEqual(recommended.sourceMetadata, baseline.sourceMetadata);
  assert.notEqual(
    recommended.sourceMetadata.sourceBindings,
    baseline.sourceMetadata.sourceBindings,
  );
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
