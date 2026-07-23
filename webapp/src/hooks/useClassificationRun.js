import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, openRunEventSource, postJson } from "../lib/api.js";
import { clean } from "../lib/format.js";

export const JOB_STORAGE_KEY = "asap-cjs-job-id";

const ACTIVE_STATUSES = ["submitting", "queued", "running"];

function ReadStoredJobId() {
  try {
    return window.sessionStorage.getItem(JOB_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function StoreJobId(jobId) {
  try {
    if (jobId) window.sessionStorage.setItem(JOB_STORAGE_KEY, jobId);
  } catch {
    /* sessionStorage unavailable */
  }
}

function ClearStoredJobId() {
  try {
    window.sessionStorage.removeItem(JOB_STORAGE_KEY);
  } catch {
    /* sessionStorage unavailable */
  }
}

function IsAbortError(error) {
  return error?.name === "AbortError";
}

export function IsCurrentRunOperation(currentOperationId, candidateOperationId) {
  return currentOperationId === candidateOperationId;
}

export function useClassificationRun(initialJobId = "") {
  const [result, setResultState] = useState(null);
  const [restoring, setRestoring] = useState(false);
  const [restorableJobId, setRestorableJobId] = useState("");
  const sseRef = useRef(null);
  const resultRef = useRef(null);
  const operationIdRef = useRef(0);
  const requestAbortRef = useRef(null);

  const SetResult = useCallback((next) => {
    resultRef.current = next || {};
    setResultState(resultRef.current);
  }, []);

  const RememberRestorableJob = useCallback((jobId) => {
    const normalizedJobId = clean(jobId);
    if (!normalizedJobId) return;
    StoreJobId(normalizedJobId);
    setRestorableJobId(normalizedJobId);
  }, []);

  const CloseSse = useCallback(() => {
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
  }, []);

  const BeginOperation = useCallback(() => {
    operationIdRef.current += 1;
    requestAbortRef.current?.abort();
    const controller = new AbortController();
    requestAbortRef.current = controller;
    return { id: operationIdRef.current, signal: controller.signal };
  }, []);

  const IsCurrentOperation = useCallback((operation) => (
    IsCurrentRunOperation(operationIdRef.current, operation.id)
  ), []);

  const HydrateRun = useCallback(async (jobId, operation) => {
    const snapshot = await getJson(
      `/api/runs/${encodeURIComponent(jobId)}`,
      { signal: operation.signal },
    );
    if (!IsCurrentOperation(operation)) return null;
    SetResult(snapshot);
    RememberRestorableJob(clean(snapshot?.job_id) || jobId);
    return snapshot;
  }, [IsCurrentOperation, RememberRestorableJob, SetResult]);

  const OpenSse = useCallback((jobId, operation) => {
    if (!IsCurrentOperation(operation)) return;
    CloseSse();
    const currentEvents = Array.isArray(resultRef.current?.events)
      ? resultRef.current.events.length
      : 0;
    const source = openRunEventSource(jobId, currentEvents);
    sseRef.current = source;

    const IsCurrentSource = () => (
      IsCurrentOperation(operation) && sseRef.current === source
    );

    source.addEventListener("pipeline_event", (event) => {
      if (!IsCurrentSource()) return;
      try {
        const payload = JSON.parse(event.data || "{}");
        const previous = resultRef.current || {};
        const nextEvents = Array.isArray(previous.events) ? previous.events.slice() : [];
        nextEvents.push(payload);
        const partial = payload.partial_result && typeof payload.partial_result === "object"
          ? payload.partial_result
          : {};
        SetResult({
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
        source.close();
        if (sseRef.current === source) sseRef.current = null;
        SetResult({ ...(resultRef.current || {}), job_status: "failed", error: String(error) });
      }
    });

    source.addEventListener("run_complete", async () => {
      if (!IsCurrentSource()) return;
      source.close();
      sseRef.current = null;
      try {
        await HydrateRun(jobId, operation);
      } catch (error) {
        if (IsAbortError(error) || !IsCurrentOperation(operation)) return;
        const previous = resultRef.current || {};
        SetResult({
          ...previous,
          job_id: jobId,
          job_status: clean(previous.job_status) || "failed",
          error: previous.error || `최종 실행 결과를 불러오지 못했습니다. ${String(error?.message || error)}`,
        });
      }
    });
  }, [CloseSse, HydrateRun, IsCurrentOperation, SetResult]);

  const loadRun = useCallback(async (jobId) => {
    const targetJobId = clean(jobId);
    if (!targetJobId) throw new Error("job_id를 입력하세요.");
    const operation = BeginOperation();
    CloseSse();
    setRestoring(true);
    try {
      const snapshot = await HydrateRun(targetJobId, operation);
      if (
        snapshot
        && ACTIVE_STATUSES.includes(clean(snapshot.job_status).toLowerCase())
      ) {
        OpenSse(targetJobId, operation);
      }
      return snapshot;
    } catch (error) {
      if (IsAbortError(error) || !IsCurrentOperation(operation)) return null;
      throw error;
    } finally {
      if (IsCurrentOperation(operation)) setRestoring(false);
    }
  }, [BeginOperation, CloseSse, HydrateRun, IsCurrentOperation, OpenSse]);

  const runPipeline = useCallback(async (mode, form) => {
    const operation = BeginOperation();
    CloseSse();
    setRestoring(false);
    const productName = clean(form.productName);
    const url = clean(form.url);
    const ingredients = (Array.isArray(form.ingredients) ? form.ingredients : [])
      .filter((item) => clean(item?.name) || clean(item?.percentage))
      .map((item) => ({
        role: item.role,
        name: clean(item.name),
        percentage: Number(item.percentage),
      }));
    const inputFacts = {};
    if (ingredients.length) inputFacts.ingredients = ingredients;
    if (clean(form.intendedUse)) inputFacts.intended_use = clean(form.intendedUse);
    if (clean(form.originCountry)) {
      inputFacts.origin_country = clean(form.originCountry).toUpperCase();
    }
    const previousFacts = resultRef.current?.request?.facts || {};
    const cachedQuery = mode === "cached"
      ? clean(previousFacts.product_name) || clean(previousFacts.product_id)
      : "";
    const payload = {
      query: productName || url || cachedQuery,
      product_name: productName,
      url,
      input_facts: inputFacts,
      facts: {
        product_name: productName,
        url,
        source_urls: url ? [url] : [],
      },
    };
    const requestFacts = {
      ...payload.facts,
      ...(Object.keys(inputFacts).length ? { user_input_facts: inputFacts } : {}),
    };

    if (mode === "reconstruct" && !url && !clean(previousFacts.product_id)) {
      SetResult({
        job_status: "failed",
        error: "상품 정보 복원에는 상품 URL 또는 기존 작업의 product_id가 필요합니다.",
        events: [{ stage: "Input", status: "failed", message: "복원 대상 없음" }],
      });
      return null;
    }
    if (!payload.query && !previousFacts.product_id) {
      SetResult({
        job_status: "failed",
        error: "제품명 또는 URL 중 하나는 입력해야 합니다.",
        events: [{ stage: "Input", status: "failed", message: "입력값 없음" }],
      });
      return null;
    }

    SetResult({
      job_status: "submitting",
      request: { query: payload.query, facts: requestFacts },
      events: [{ stage: "Pipeline", status: "submitting", message: "작업 등록 중" }],
    });

    let submittedJobId = "";
    try {
      if (mode === "reconstruct") {
        const body = await postJson(
          "/api/reconstruction-runs",
          {
            url: payload.facts.url,
            product_id: clean(previousFacts.product_id),
          },
          { signal: operation.signal },
        );
        if (!IsCurrentOperation(operation)) return null;
        SetResult(body);
        return body;
      }
      if (mode === "cached") {
        payload.facts.use_cached_product_input = true;
        if (previousFacts.product_id) payload.facts.product_id = previousFacts.product_id;
      }
      const accepted = await postJson("/api/runs", payload, { signal: operation.signal });
      if (!IsCurrentOperation(operation)) return null;
      submittedJobId = clean(accepted.job_id);
      RememberRestorableJob(submittedJobId);
      SetResult({
        job_id: submittedJobId,
        job_status: accepted.status || "queued",
        request: { query: payload.query, facts: requestFacts },
        events: [
          {
            stage: "Pipeline",
            status: accepted.status || "queued",
            message: "작업 등록 완료",
          },
        ],
      });
      const snapshot = await HydrateRun(submittedJobId, operation);
      if (snapshot) OpenSse(submittedJobId, operation);
      return snapshot;
    } catch (error) {
      if (IsAbortError(error) || !IsCurrentOperation(operation)) return null;
      SetResult({
        ...(submittedJobId ? { job_id: submittedJobId } : {}),
        job_status: "failed",
        error: String(error?.message || error),
        request: { query: payload.query, facts: requestFacts },
        events: [
          { stage: "Pipeline", status: "failed", message: String(error?.message || error) },
        ],
      });
      return null;
    }
  }, [
    BeginOperation,
    CloseSse,
    HydrateRun,
    IsCurrentOperation,
    OpenSse,
    RememberRestorableJob,
    SetResult,
  ]);

  useEffect(() => {
    const targetJobId = clean(initialJobId) || ReadStoredJobId();
    if (!targetJobId || clean(resultRef.current?.job_id) === targetJobId) return undefined;
    const operation = BeginOperation();
    CloseSse();
    setRestoring(true);
    HydrateRun(targetJobId, operation)
      .then((snapshot) => {
        if (
          snapshot
          && ACTIVE_STATUSES.includes(clean(snapshot.job_status).toLowerCase())
        ) {
          OpenSse(targetJobId, operation);
        }
      })
      .catch((error) => {
        if (IsAbortError(error) || !IsCurrentOperation(operation)) return;
        if (!clean(initialJobId)) ClearStoredJobId();
        SetResult({
          job_id: targetJobId,
          job_status: "failed",
          error: String(error?.message || error),
          events: [{ stage: "Restore", status: "failed", message: "기존 작업 복원 실패" }],
        });
      })
      .finally(() => {
        if (IsCurrentOperation(operation)) setRestoring(false);
      });
    return undefined;
  }, [
    BeginOperation,
    CloseSse,
    HydrateRun,
    IsCurrentOperation,
    OpenSse,
    SetResult,
    initialJobId,
  ]);

  useEffect(() => () => {
    operationIdRef.current += 1;
    requestAbortRef.current?.abort();
    CloseSse();
  }, [CloseSse]);

  const busy = restoring || ACTIVE_STATUSES.includes(clean(result?.job_status).toLowerCase());

  return { result, busy, restoring, restorableJobId, runPipeline, loadRun };
}
