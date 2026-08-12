import assert from "node:assert/strict";
import test from "node:test";
import { NormalizeWarning } from "./warningViewModel.js";

test("구조화된 경고 심각도를 우선 사용한다", () => {
  assert.equal(NormalizeWarning({ message: "중단", severity: "blocking" }).severity, "blocking");
  assert.equal(NormalizeWarning({ message: "검토", severity: "needs_review" }).severity, "needs-review");
  assert.equal(NormalizeWarning({ message: "참고", severity: "informational" }).severity, "informational");
  assert.equal(NormalizeWarning({ message: "참고", severity: "info" }).severitySource, "contract");
});

test("기존 한국어 경고는 한 곳에서 검토 필요로 추정한다", () => {
  const warning = NormalizeWarning("OCR 근거가 부족해 값을 유보했습니다.");
  assert.equal(warning.severity, "needs-review");
  assert.equal(warning.severitySource, "heuristic");
});

test("영문 오류 경고도 검토 필요로 정규화한다", () => {
  assert.equal(NormalizeWarning("Evidence unavailable").severity, "needs-review");
});

test("판단할 수 없는 문자열은 informational로 둔다", () => {
  const warning = NormalizeWarning("Pipeline message received");
  assert.equal(warning.severity, "informational");
  assert.equal(warning.severitySource, "default");
});

test("단순 확인 문구를 처리 차단으로 과장하지 않는다", () => {
  assert.equal(NormalizeWarning("상품 정보를 확인했습니다.").severity, "informational");
});

test("빈 경고는 렌더링 모델을 만들지 않는다", () => {
  assert.equal(NormalizeWarning(""), null);
  assert.equal(NormalizeWarning({}), null);
  assert.equal(NormalizeWarning(null), null);
  assert.equal(NormalizeWarning(undefined), null);
});

test("JSON 문자열 경고는 구조화 값으로 복구한다", () => {
  const warning = NormalizeWarning(
    '{"code":"OCR_MISSING","detail":"OCR 근거 부족","severity":"needs_review","field":"origin"}',
  );

  assert.deepEqual(warning, {
    code: "OCR_MISSING",
    message: "OCR 근거 부족",
    severity: "needs-review",
    field: "origin",
    source: "",
    severitySource: "serialized-contract",
  });
});

test("경고 객체가 아닌 JSON과 잘못된 JSON 원문은 노출하지 않는다", () => {
  assert.equal(NormalizeWarning('{"value":"not a warning"}'), null);
  assert.equal(NormalizeWarning("{invalid json}"), null);
});
