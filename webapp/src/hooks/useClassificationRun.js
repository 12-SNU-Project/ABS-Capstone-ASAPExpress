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

export function useClassificationRun(initialJobId = "") {
  const [result, setResultState] = useState(null);
  const [answerBusy, setAnswerBusy] = useState(false);
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

  // 프로젝트 화면에서 기존 job_id를 직접 열 때 사용한다.
  // 조회에 성공한 경우에만 결과를 교체하므로, 잘못된 job_id 입력이 현재 화면을 지우지 않는다.
  const loadRun = useCallback(async (jobId) => {
    const targetJobId = clean(jobId);
    if (!targetJobId) {
      throw new Error("job_id를 입력하세요.");
    }
    closeSse();
    const snapshot = await hydrateRun(targetJobId);
    if (ACTIVE_STATUSES.includes(clean(snapshot?.job_status).toLowerCase())) {
      openSse(targetJobId);
    }
    return snapshot;
  }, [closeSse, hydrateRun, openSse]);

  const runPipeline = useCallback(async (mode, form) => {
    const productName = clean(form.productName);
    const url = clean(form.url);
    const ingredients = (Array.isArray(form.ingredients) ? form.ingredients : [])
      .filter((item) => clean(item?.name) || clean(item?.percentage))
      .map((item) => ({
        role: item.role,
        name: clean(item.name),
        percentage: Number(item.percentage),
      }));
    const inputFacts = { ingredients };
    if (clean(form.intendedUse)) {
      inputFacts.intended_use = clean(form.intendedUse);
    }
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

    if (!payload.query && !previousFacts.product_id) {
      setResult({
        job_status: "failed",
        error: "제품명 또는 URL 중 하나는 입력해야 합니다.",
        events: [{ stage: "Input", status: "failed", message: "입력값 없음" }],
      });
      return;
    }

    closeSse();
    setResult({
      job_status: "submitting",
      request: { query: payload.query, facts: requestFacts },
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
        request: { query: payload.query, facts: requestFacts },
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
        request: { query: payload.query, facts: requestFacts },
        events: [
          { stage: "Pipeline", status: "failed", message: String(error?.message || error) },
        ],
      });
    }
  }, [closeSse, hydrateRun, openSse, setResult]);

  const answerQuestions = useCallback(async (answers) => {
    const jobId = clean(resultRef.current?.job_id);
    if (!jobId) {
      throw new Error("답변을 반영할 실행 ID가 없습니다.");
    }
    const normalizedAnswers = (Array.isArray(answers) ? answers : [])
      .filter((item) => clean(item?.user_question_id) && clean(item?.answer))
      .map((item) => ({
        user_question_id: clean(item.user_question_id),
        answer: clean(item.answer).toLowerCase(),
      }));
    if (!normalizedAnswers.length) {
      throw new Error("답변을 하나 이상 선택하세요.");
    }
    setAnswerBusy(true);
    try {
      const snapshot = await postJson(
        `/api/runs/${encodeURIComponent(jobId)}/question-answers`,
        { answers: normalizedAnswers },
      );
      setResult(snapshot);
      return snapshot;
    } finally {
      setAnswerBusy(false);
    }
  }, [setResult]);

  // 상세 화면의 job 쿼리를 우선하고, 없으면 최근 run을 복원한다.
  useEffect(() => {
    const targetJobId = clean(initialJobId) || readStoredJobId();
    if (!targetJobId || clean(resultRef.current?.job_id) === targetJobId) {
      return undefined;
    }
    hydrateRun(targetJobId)
      .then((snapshot) => {
        if (ACTIVE_STATUSES.includes(clean(snapshot?.job_status).toLowerCase())) {
          openSse(targetJobId);
        }
      })
      .catch(() => {
        if (!clean(initialJobId)) {
          clearStoredJobId();
        }
      });
    return undefined;
  }, [hydrateRun, initialJobId, openSse]);

  useEffect(() => closeSse, [closeSse]);

  const busy =
    answerBusy || ACTIVE_STATUSES.includes(clean(result?.job_status).toLowerCase());

  return { result, busy, runPipeline, loadRun, answerQuestions };
}
