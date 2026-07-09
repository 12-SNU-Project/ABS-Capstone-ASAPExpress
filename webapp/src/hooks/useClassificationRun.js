import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, openRunEventSource, postJson } from "../lib/api.js";
import { clean } from "../lib/format.js";

export const JOB_STORAGE_KEY = "asap-cjs-job-id";

const ACTIVE_STATUSES = ["submitting", "queued", "running"];

function readStoredJobId() {
  try {
    return window.sessionStorage.getItem(JOB_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function storeJobId(jobId) {
  try {
    if (jobId) {
      window.sessionStorage.setItem(JOB_STORAGE_KEY, jobId);
    }
  } catch {
    /* sessionStorage unavailable */
  }
}

function clearStoredJobId() {
  try {
    window.sessionStorage.removeItem(JOB_STORAGE_KEY);
  } catch {
    /* sessionStorage unavailable */
  }
}

export function useClassificationRun() {
  const [result, setResultState] = useState(null);
  const sseRef = useRef(null);
  const resultRef = useRef(null);

  const setResult = useCallback((next) => {
    resultRef.current = next || {};
    storeJobId(clean(resultRef.current.job_id));
    setResultState(resultRef.current);
  }, []);

  const closeSse = useCallback(() => {
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
  }, []);

  const hydrateRun = useCallback(async (jobId) => {
    const snapshot = await getJson(`/api/runs/${encodeURIComponent(jobId)}`);
    setResult(snapshot);
    return snapshot;
  }, [setResult]);

  const openSse = useCallback((jobId) => {
    closeSse();
    const currentEvents = Array.isArray(resultRef.current?.events)
      ? resultRef.current.events.length
      : 0;
    const source = openRunEventSource(jobId, currentEvents);
    sseRef.current = source;

    source.addEventListener("pipeline_event", (event) => {
      try {
        const payload = JSON.parse(event.data || "{}");
        const previous = resultRef.current || {};
        const nextEvents = Array.isArray(previous.events) ? previous.events.slice() : [];
        nextEvents.push(payload);
        const partial =
          payload.partial_result && typeof payload.partial_result === "object"
            ? payload.partial_result
            : {};
        setResult({
          ...previous,
          ...partial,
          job_id: jobId,
          job_status:
            payload.stage === "Pipeline" && ["completed", "failed"].includes(payload.status)
              ? payload.status
              : "running",
          events: nextEvents,
        });
      } catch (error) {
        setResult({ ...(resultRef.current || {}), job_status: "failed", error: String(error) });
      }
    });

    source.addEventListener("run_complete", async () => {
      source.close();
      sseRef.current = null;
      try {
        await hydrateRun(jobId);
      } catch {
        setResult({ ...(resultRef.current || {}), job_status: "completed" });
      }
    });
  }, [closeSse, hydrateRun, setResult]);

  const runPipeline = useCallback(async (mode, form) => {
    const productName = clean(form.productName);
    const description = clean(form.description);
    const url = clean(form.url);
    const previousFacts = resultRef.current?.request?.facts || {};
    const payload = {
      query: productName || description || url,
      product_name: productName,
      description,
      url,
      facts: {
        product_name: productName,
        description,
        url,
        source_urls: url ? [url] : [],
        origin_country: "KR",
        intended_use: "human consumption",
      },
    };

    if (!payload.query && !previousFacts.product_id) {
      setResult({
        job_status: "failed",
        error: "제품명, 설명, URL 중 하나는 입력해야 합니다.",
        events: [{ stage: "Input", status: "failed", message: "입력값 없음" }],
      });
      return;
    }

    closeSse();
    setResult({
      job_status: "submitting",
      request: { query: payload.query, facts: payload.facts },
      events: [{ stage: "Pipeline", status: "submitting", message: "작업 등록 중" }],
    });

    try {
      if (mode === "reconstruct") {
        const body = await postJson("/api/reconstruction-runs", {
          url: payload.facts.url,
          product_id: clean(previousFacts.product_id),
        });
        setResult(body);
        return;
      }
      if (mode === "cached") {
        payload.facts.use_cached_product_input = true;
        if (previousFacts.product_id) {
          payload.facts.product_id = previousFacts.product_id;
        }
      }
      const accepted = await postJson("/api/runs", payload);
      setResult({
        job_id: accepted.job_id,
        job_status: accepted.status || "queued",
        request: { query: payload.query, facts: payload.facts },
        events: [
          {
            stage: "Pipeline",
            status: accepted.status || "queued",
            message: "작업 등록 완료",
          },
        ],
      });
      await hydrateRun(accepted.job_id);
      openSse(accepted.job_id);
    } catch (error) {
      setResult({
        job_status: "failed",
        error: String(error?.message || error),
        request: { query: payload.query, facts: payload.facts },
        events: [
          { stage: "Pipeline", status: "failed", message: String(error?.message || error) },
        ],
      });
    }
  }, [closeSse, hydrateRun, openSse, setResult]);

  // 서류 페이지 왕복/새로고침 후 최근 run 복원
  useEffect(() => {
    const storedJobId = readStoredJobId();
    if (!storedJobId || resultRef.current?.job_id) {
      return undefined;
    }
    hydrateRun(storedJobId)
      .then((snapshot) => {
        if (ACTIVE_STATUSES.includes(clean(snapshot?.job_status).toLowerCase())) {
          openSse(storedJobId);
        }
      })
      .catch(() => clearStoredJobId());
    return undefined;
  }, [hydrateRun, openSse]);

  useEffect(() => closeSse, [closeSse]);

  const busy = ACTIVE_STATUSES.includes(clean(result?.job_status).toLowerCase());

  return { result, busy, runPipeline };
}
