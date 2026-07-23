import { asObject, clean } from "../../../lib/format.js";

const SEVERITY_ALIASES = {
  blocking: "blocking",
  error: "blocking",
  fatal: "blocking",
  "needs-review": "needs-review",
  needs_review: "needs-review",
  review_required: "needs-review",
  warning: "needs-review",
  informational: "informational",
  info: "informational",
};

function InferSeverity(message) {
  if (/(처리\s*차단|치명적|\bblocking\b|\bfatal\b)/i.test(message)) return "blocking";
  if (/(근거\s*부족|유보|사용할 수 없|오류|실패|확인\s*필요|missing evidence|unavailable|not found|\berror\b|\bfailed\b|\bfailure\b|needs review|review required)/i.test(message)) {
    return "needs-review";
  }
  return "";
}

export function NormalizeWarning(warning, { defaultSeverity = "informational" } = {}) {
  const sourceWarning = typeof warning === "string" ? {} : asObject(warning);
  const message = clean(
    typeof warning === "string"
      ? warning
      : sourceWarning.message || sourceWarning.detail || sourceWarning.warning || sourceWarning.code,
  );
  if (!message) return null;

  const contractSeverity = SEVERITY_ALIASES[clean(sourceWarning.severity).toLowerCase()];
  const heuristicSeverity = contractSeverity ? "" : InferSeverity(message);
  const fallbackSeverity = SEVERITY_ALIASES[clean(defaultSeverity).toLowerCase()] || "informational";
  return {
    code: clean(sourceWarning.code),
    message,
    severity: contractSeverity || heuristicSeverity || fallbackSeverity,
    field: clean(sourceWarning.field),
    source: clean(sourceWarning.source),
    severitySource: contractSeverity ? "contract" : heuristicSeverity ? "heuristic" : "default",
  };
}
