import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, openRunEventSource, postJson } from "../lib/api.js";
import { clean } from "../lib/format.js";

export const JOB_STORAGE_KEY = "asap-cjs-job-id";

const ACTIVE_STATUSES = ["submitting", "queued", "running"];

export function ShouldConnectRunSnapshot(snapshot) {
  return ACTIVE_STATUSES.includes(clean(snapshot?.job_status).toLowerCase());
}

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

export function CreateRunLifecycle() {
  let activeOperationId = 0;
  let activeController = null;
  let restoreOperationId = 0;
  let restoreController = null;
  let eventSource = null;

  function CloseEventSource() {
    if (!eventSource) return;
    eventSource.close();
    eventSource = null;
  }

  function BeginActiveOperation() {
    activeOperationId += 1;
    activeController?.abort();
    activeController = new AbortController();
    return { id: activeOperationId, signal: activeController.signal };
  }

  function BeginRestoreOperation() {
    restoreOperationId += 1;
    restoreController?.abort();
    restoreController = new AbortController();
    return { id: restoreOperationId, signal: restoreController.signal };
  }

  function CancelRestoreOperation() {
    restoreOperationId += 1;
    restoreController?.abort();
    restoreController = null;
  }

  function IsCurrentActiveOperation(operation) {
    return IsCurrentRunOperation(activeOperationId, operation?.id);
  }

  function IsCurrentRestoreOperation(operation) {
    return IsCurrentRunOperation(restoreOperationId, operation?.id);
  }

  function CommitRestoreOperation(operation) {
    if (!IsCurrentRestoreOperation(operation)) return null;
    const activeOperation = BeginActiveOperation();
    CloseEventSource();
    return activeOperation;
  }

  function AttachEventSource(source) {
    if (eventSource === source) return;
    CloseEventSource();
    eventSource = source;
  }

  function ReleaseEventSource(source) {
    if (eventSource === source) eventSource = null;
  }

  function IsCurrentEventSource(source, operation) {
    return eventSource === source && IsCurrentActiveOperation(operation);
  }

  function Dispose() {
    activeOperationId += 1;
    restoreOperationId += 1;
    activeController?.abort();
    restoreController?.abort();
    CloseEventSource();
  }

  return {
    AttachEventSource,
    BeginActiveOperation,
    BeginRestoreOperation,
    CancelRestoreOperation,
    CloseEventSource,
    CommitRestoreOperation,
    Dispose,
    IsCurrentActiveOperation,
    IsCurrentEventSource,
    IsCurrentRestoreOperation,
    ReleaseEventSource,
  };
}

export function ShouldPrepareRunTransition(targetJobId, currentJobId) {
  const target = clean(targetJobId);
  return Boolean(target) && target !== clean(currentJobId);
}

export async function PrepareRunSnapshot(targetJobId, lifecycle, loadSnapshot) {
  const restoreOperation = lifecycle.BeginRestoreOperation();
  try {
    const snapshot = await loadSnapshot(restoreOperation.signal);
    if (!lifecycle.IsCurrentRestoreOperation(restoreOperation)) {
      return { status: "stale", restoreOperation };
    }
    return { status: "ready", restoreOperation, snapshot, targetJobId };
  } catch (error) {
    if (IsAbortError(error) || !lifecycle.IsCurrentRestoreOperation(restoreOperation)) {
      return { status: "stale", restoreOperation };
    }
    return { status: "failed", restoreOperation, error };
  }
}

export function useClassificationRun(initialJobId = "") {
  const [result, setResultState] = useState(null);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState("");
  const [restorableJobId, setRestorableJobId] = useState("");
  const [answering, setAnswering] = useState(false);
  const [answerError, setAnswerError] = useState("");
  const resultRef = useRef(null);
  const lifecycleRef = useRef(null);
  if (!lifecycleRef.current) lifecycleRef.current = CreateRunLifecycle();
  const lifecycle = lifecycleRef.current;

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

  const BeginOperation = useCallback(() => {
    lifecycle.CancelRestoreOperation();
    return lifecycle.BeginActiveOperation();
  }, [lifecycle]);

  const IsCurrentOperation = useCallback((operation) => (
    lifecycle.IsCurrentActiveOperation(operation)
  ), [lifecycle]);

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
    const currentEvents = Array.isArray(resultRef.current?.events)
      ? resultRef.current.events.length
      : 0;
    const source = openRunEventSource(jobId, currentEvents);
    lifecycle.AttachEventSource(source);

    const IsCurrentSource = () => (
      lifecycle.IsCurrentEventSource(source, operation)
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
        const nextStatus = ["awaiting_input", "completed", "failed"].includes(payload.status)
          ? payload.status
          : "running";
        SetResult({
          ...previous,
          ...partial,
          job_id: jobId,
          job_status: nextStatus,
          events: nextEvents,
        });
      } catch (error) {
        source.close();
        lifecycle.ReleaseEventSource(source);
        SetResult({ ...(resultRef.current || {}), job_status: "failed", error: String(error) });
      }
    });

    const FinishStream = async () => {
      if (!IsCurrentSource()) return;
      source.close();
      lifecycle.ReleaseEventSource(source);
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
    };
    source.addEventListener("run_complete", FinishStream);
    source.addEventListener("run_paused", FinishStream);
  }, [HydrateRun, IsCurrentOperation, SetResult, lifecycle]);

  const clearRestoreError = useCallback(() => setRestoreError(""), []);

  const PrepareAndCommitRunTransition = useCallback(async (
    jobId,
    { clearStoredOnFailure = false } = {},
  ) => {
    const targetJobId = clean(jobId);
    if (!targetJobId) {
      setRestoreError("job_id를 입력하세요.");
      return null;
    }
    if (!ShouldPrepareRunTransition(targetJobId, resultRef.current?.job_id)) {
      setRestoreError("");
      return resultRef.current;
    }
    setRestoreError("");
    setRestoring(true);
    let restoreOperation = null;
    try {
      const preparation = await PrepareRunSnapshot(
        targetJobId,
        lifecycle,
        (signal) => getJson(
          `/api/runs/${encodeURIComponent(targetJobId)}`,
          { signal },
        ),
      );
      restoreOperation = preparation.restoreOperation;
      if (preparation.status === "stale") return null;
      if (preparation.status === "failed") throw preparation.error;
      const snapshot = preparation.snapshot;
      const operation = lifecycle.CommitRestoreOperation(restoreOperation);
      if (!operation) return null;
      const restoredJobId = clean(snapshot?.job_id) || targetJobId;
      SetResult(snapshot);
      RememberRestorableJob(restoredJobId);
      if (ShouldConnectRunSnapshot(snapshot)) {
        OpenSse(restoredJobId, operation);
      }
      return snapshot;
    } catch (error) {
      if (IsAbortError(error) || !lifecycle.IsCurrentRestoreOperation(restoreOperation)) {
        return null;
      }
      if (clearStoredOnFailure) ClearStoredJobId();
      setRestoreError(`작업을 불러오지 못했습니다. ${String(error?.message || error)}`);
      return null;
    } finally {
      if (restoreOperation && lifecycle.IsCurrentRestoreOperation(restoreOperation)) {
        setRestoring(false);
      }
    }
  }, [OpenSse, RememberRestorableJob, SetResult, lifecycle]);

  const loadRun = useCallback(
    (jobId) => PrepareAndCommitRunTransition(jobId),
    [PrepareAndCommitRunTransition],
  );

  const runPipeline = useCallback(async (mode, form) => {
    const operation = BeginOperation();
    lifecycle.CloseEventSource();
    setRestoreError("");
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
      if (snapshot && ShouldConnectRunSnapshot(snapshot)) {
        OpenSse(submittedJobId, operation);
      }
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
    HydrateRun,
    IsCurrentOperation,
    OpenSse,
    RememberRestorableJob,
    SetResult,
    lifecycle,
  ]);

  const answerQuestions = useCallback(async (answers) => {
    const jobId = clean(resultRef.current?.job_id);
    if (!jobId) return null;
    const operation = BeginOperation();
    lifecycle.CloseEventSource();
    setAnswerError("");
    setAnswering(true);
    try {
      const snapshot = await postJson(
        `/api/runs/${encodeURIComponent(jobId)}/question-answers`,
        { answers },
        { signal: operation.signal },
      );
      if (!IsCurrentOperation(operation)) return null;
      SetResult(snapshot);
      RememberRestorableJob(jobId);
      return snapshot;
    } catch (error) {
      if (IsAbortError(error) || !IsCurrentOperation(operation)) return null;
      setAnswerError(String(error?.message || error));
      return null;
    } finally {
      setAnswering(false);
    }
  }, [
    BeginOperation,
    IsCurrentOperation,
    RememberRestorableJob,
    SetResult,
    lifecycle,
  ]);

  useEffect(() => {
    const targetJobId = clean(initialJobId) || ReadStoredJobId();
    if (!targetJobId) return undefined;
    PrepareAndCommitRunTransition(targetJobId, {
      clearStoredOnFailure: !clean(initialJobId),
    });
    return undefined;
  }, [PrepareAndCommitRunTransition, initialJobId]);

  useEffect(() => () => lifecycle.Dispose(), [lifecycle]);

  const busy = restoring
    || answering
    || ACTIVE_STATUSES.includes(clean(result?.job_status).toLowerCase());

  return {
    result,
    busy,
    restoring,
    answering,
    answerError,
    restoreError,
    restorableJobId,
    runPipeline,
    answerQuestions,
    loadRun,
    clearRestoreError,
  };
}
