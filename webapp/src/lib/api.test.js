import assert from "node:assert/strict";
import test from "node:test";
import { readJson } from "./api.js";

test("JSON이 아닌 API 오류는 파싱 예외 대신 HTTP 상태를 전달한다", async () => {
  const response = new Response("<html>Bad Gateway</html>", {
    status: 502,
    statusText: "Bad Gateway",
  });
  await assert.rejects(() => readJson(response), /502 Bad Gateway/);
});
