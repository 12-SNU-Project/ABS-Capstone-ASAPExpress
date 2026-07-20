import { buildUrl, getJson, postJson, readJson } from "./api.js";

const BASE = "/api/enterprise";

function call(action, payload, { method = "POST" } = {}) {
  if (method === "GET") {
    const query = new URLSearchParams(payload || {}).toString();
    return getJson(`${BASE}/${action}${query ? `?${query}` : ""}`);
  }
  return postJson(`${BASE}/${action}`, payload);
}

export const registerProduct = (payload) => call("register-product", payload);
export const reportDocStatus = (payload) => call("doc-status", payload);
export const submitDocRequest = (payload) => call("doc-request", payload);
export const issueSubmitUrl = (payload) => call("issue-url", payload);
export const normalizeCoi = (payload) => call("coi-normalize", payload);
export const linkJob = (payload) => call("link-job", payload);
export const fetchBrokerFiling = (caseId) => call("broker-filing", { caseId }, { method: "GET" });
export const fetchCases = () => call("cases", {}, { method: "GET" });
export const importClassification = (payload) => call("import-classification", payload);

export async function uploadDocument(caseId, documentKey, file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    buildUrl(`${BASE}/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(documentKey)}/upload`),
    { method: "POST", body: form },
  );
  return readJson(response);
}
