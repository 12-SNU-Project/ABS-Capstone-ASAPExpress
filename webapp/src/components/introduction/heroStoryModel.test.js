import assert from "node:assert/strict";
import test from "node:test";
import { GetNextStoryIndex } from "./heroStoryModel.js";

test("GetNextStoryIndex advances and loops the editorial figure", () => {
  assert.equal(GetNextStoryIndex(1, 4), 2);
  assert.equal(GetNextStoryIndex(3, 4), 0);
  assert.equal(GetNextStoryIndex(0, 0), 0);
});
