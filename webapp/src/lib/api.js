function cleanText(value) {
  return String(value ?? "").trim();
}

export function buildUrl(path) {
  const baseUrl = cleanText(import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
  return baseUrl ? `${baseUrl}${path}` : path;
}

export async function readJson(response) {
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(
        response.ok
          ? "JSON object response expected."
          : `${response.status} ${response.statusText}`,
      );
    }
  }
  if (!response.ok) {
    const message =
      (payload && typeof payload === "object" && (payload.message || payload.error || payload.hint)) ||
      `${response.status} ${response.statusText}`;
    throw new Error(String(message));
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("JSON object response expected.");
  }
  return payload;
}

export async function getJson(path, { signal } = {}) {
  const response = await fetch(buildUrl(path), {
    headers: { Accept: "application/json" },
    signal,
  });
  return readJson(response);
}

export async function postJson(path, body, { signal } = {}) {
  const response = await fetch(buildUrl(path), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body ?? {}),
    signal,
  });
  return readJson(response);
}

export function openRunEventSource(jobId, startIndex = 0) {
  const url = buildUrl(
    `/api/runs/${encodeURIComponent(jobId)}/events?start=${encodeURIComponent(startIndex)}`,
  );
  return new EventSource(url);
}
