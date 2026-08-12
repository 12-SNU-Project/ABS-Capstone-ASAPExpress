import { LABELS } from "./labels.js";

const STATUS_LABELS = {
  idle: "대기",
  submitting: "등록 중",
  queued: "대기열",
  running: "실행 중",
  awaiting_input: "사용자 응답 대기",
  "awaiting-input": "사용자 응답 대기",
  completed: "완료",
  complete: "완료",
  failed: "실패",
  done: "완료",
  ok: "정상",
  warn: "확인 필요",
  "needs-review": "전문가 검토 필요",
  skipped: "건너뜀",
};

const SOURCE_LABELS = {
  candidate: "후보",
  classifier: "기존 분류기",
  staged_classifier: "단계별 규칙 분류",
  proposed: "제안 후보",
};

export function clean(value) {
  return String(value ?? "").trim();
}

export function asList(value) {
  return Array.isArray(value) ? value : [];
}

export function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

export function optionalFiniteNumber(value) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function isFilled(value) {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return clean(value) !== "";
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  return true;
}

export function previewValue(value, limit = 160) {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "boolean") {
    return value ? "예" : "아니오";
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    const compact = clean(value).replace(/\s+/g, " ");
    return compact.length > limit ? `${compact.slice(0, limit)}…` : compact;
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return "";
    }
    const primitiveOnly = value.every(
      (item) => item === null || ["string", "number", "boolean"].includes(typeof item),
    );
    if (primitiveOnly) {
      return previewValue(value.map((item) => previewValue(item, 40)).join(", "), limit);
    }
    return previewValue(JSON.stringify(value), limit);
  }
  if (typeof value === "object") {
    return previewValue(JSON.stringify(value), limit);
  }
  return previewValue(String(value), limit);
}

export function formatValue(value, limit = 160) {
  return previewValue(value, limit);
}

export function labelFor(key) {
  return LABELS[key] || key;
}

export function statusLabel(status) {
  const key = clean(status).toLowerCase();
  return STATUS_LABELS[key] || clean(status) || "대기";
}

export function sourceLabel(source) {
  const key = clean(source).toLowerCase();
  return SOURCE_LABELS[key] || clean(source) || "후보";
}

export function candidateKey(candidate, index) {
  const source = asObject(candidate);
  return clean(source.candidate_id || source.cn8 || source.taric10 || `candidate_${index}`);
}
