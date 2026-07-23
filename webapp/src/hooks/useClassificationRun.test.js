import assert from "node:assert/strict";
import test from "node:test";
import { IsCurrentRunOperation } from "./useClassificationRun.js";

test("늦게 도착한 이전 작업 응답은 현재 작업으로 인정하지 않는다", () => {
  assert.equal(IsCurrentRunOperation(2, 1), false);
  assert.equal(IsCurrentRunOperation(2, 2), true);
});
