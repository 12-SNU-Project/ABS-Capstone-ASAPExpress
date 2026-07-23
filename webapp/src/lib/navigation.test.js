import assert from "node:assert/strict";
import test from "node:test";
import { ResolveExpertToolbarSection } from "./navigation.js";

test("서류 상세의 진입 맥락에 맞는 전문가 툴바를 표시한다", () => {
  assert.equal(ResolveExpertToolbarSection("/classification"), "/classification");
  assert.equal(ResolveExpertToolbarSection("/admin"), "/classification");
  assert.equal(ResolveExpertToolbarSection("/document/job/code"), "/classification");
  assert.equal(
    ResolveExpertToolbarSection("/document/job/code", "?caseId=case_123"),
    "/enterprise",
  );
});
