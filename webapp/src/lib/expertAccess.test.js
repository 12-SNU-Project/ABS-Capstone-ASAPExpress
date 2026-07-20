import assert from "node:assert/strict";
import test from "node:test";
import {
  IsValidExpertAccessCode,
  ResolveAccessMode,
  ResolveExpertToolbarSection,
} from "./expertAccess.js";

test("전문가 접근 코드는 asap-dev만 허용한다", () => {
  assert.equal(IsValidExpertAccessCode("asap-dev"), true);
  assert.equal(IsValidExpertAccessCode(" asap-dev "), true);
  assert.equal(IsValidExpertAccessCode("wrong-code"), false);
});

test("현재 화면과 저장된 선택으로 툴바 모드를 결정한다", () => {
  assert.equal(ResolveAccessMode("/consumer", "expert"), "guest");
  assert.equal(ResolveAccessMode("/classification", "guest"), "expert");
  assert.equal(ResolveAccessMode("/enterprise", "guest"), "expert");
  assert.equal(ResolveAccessMode("/document/job/code", "guest"), "guest");
  assert.equal(ResolveAccessMode("/document/job/code", "expert"), "expert");
  assert.equal(ResolveAccessMode("/document/job/code", "guest", "?caseId=case_123"), "expert");
});

test("서류 상세의 진입 맥락에 맞는 전문가 툴바를 표시한다", () => {
  assert.equal(ResolveExpertToolbarSection("/classification"), "/classification");
  assert.equal(ResolveExpertToolbarSection("/admin"), "/classification");
  assert.equal(ResolveExpertToolbarSection("/document/job/code"), "/classification");
  assert.equal(
    ResolveExpertToolbarSection("/document/job/code", "?caseId=case_123"),
    "/enterprise",
  );
});
