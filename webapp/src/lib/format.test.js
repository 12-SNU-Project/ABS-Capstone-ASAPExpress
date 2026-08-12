import assert from "node:assert/strict";
import test from "node:test";
import { optionalFiniteNumber } from "./format.js";

test("optionalFiniteNumber는 미계산 값과 실제 0점을 구분한다", () => {
  assert.equal(optionalFiniteNumber(null), null);
  assert.equal(optionalFiniteNumber(undefined), null);
  assert.equal(optionalFiniteNumber(""), null);
  assert.equal(optionalFiniteNumber(false), null);
  assert.equal(optionalFiniteNumber("invalid"), null);
  assert.equal(optionalFiniteNumber(0), 0);
  assert.equal(optionalFiniteNumber("3.5"), 3.5);
});
