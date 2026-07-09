function cleanText(value) {
  return String(value ?? "").trim();
}

function buildUrl(path) {
  const baseUrl = cleanText(import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
  return baseUrl ? `${baseUrl}${path}` : path;
}

async function readJson(response) {
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const message =
      (payload && typeof payload === "object" && (payload.message || payload.error || payload.hint)) ||
      `${response.status} ${response.statusText}`;
    throw new Error(String(message));
  }
  if (!payload || typeof payload !== "object") {
    throw new Error("JSON object response expected.");
  }
  return payload;
}

export async function getJson(path) {
  const response = await fetch(buildUrl(path), {
    headers: { Accept: "application/json" },
  });
  return readJson(response);
}

export async function postJson(path, body) {
  const response = await fetch(buildUrl(path), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body ?? {}),
  });
  return readJson(response);
}

export function openRunEventSource(jobId, startIndex = 0) {
  const url = buildUrl(
    `/api/runs/${encodeURIComponent(jobId)}/events?start=${encodeURIComponent(startIndex)}`,
  );
  return new EventSource(url);
}
