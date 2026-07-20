import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useClassificationRun } from "../hooks/useClassificationRun";
import { asList, asObject, clean } from "../lib/format.js";
import logo from "../assets/asap_black.png";

// 내부 6단계를 소비자 언어 3단계로 축약
const CONSUMER_STEPS = ["상품 정보 읽기", "코드 분류 중", "결과 정리"];

function consumerStepIndex(result) {
  const events = asList(result?.events);
  let index = 0;
  events.forEach((event) => {
    const stage = clean(event.stage);
    if (/HS2|Classification/i.test(stage)) {
      index = Math.max(index, 1);
    }
    if (/Taric|Document/i.test(stage)) {
      index = Math.max(index, 2);
    }
  });
  return index;
}

function formatCode(cn8) {
  const digits = clean(cn8);
  if (digits.length !== 8) {
    return digits || "-";
  }
  return `${digits.slice(0, 4)} ${digits.slice(4, 6)} ${digits.slice(6)}`;
}

function taricChoices(candidate) {
  const values = [
    clean(candidate?.taric10),
    ...asList(candidate?.taric10_branch_candidates).map((branch) =>
      clean(typeof branch === "object" ? branch.taric10 || branch.code : branch),
    ),
  ].filter(Boolean);
  return Array.from(new Set(values));
}

function CandidateDocuments({ candidate, jobId }) {
  const tarics = taricChoices(candidate);
  if (!jobId || !tarics.length) {
    return <div className="consumer-document-pending">TARIC10 서류 연결 준비 중</div>;
  }
  if (tarics.length === 1) {
    return (
      <Link className="consumer-document-button" to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(tarics[0])}`}>
        필요 서류 보기
      </Link>
    );
  }
  return (
    <details className="consumer-taric-picker">
      <summary>서류를 확인할 TARIC10 선택 ({tarics.length}개)</summary>
      <div className="consumer-taric-options">
        {tarics.map((taric) => (
          <Link key={taric} to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(taric)}`}>
            {taric} 서류 보기
          </Link>
        ))}
      </div>
    </details>
  );
}

export default function ConsumerPage() {
  const { result, busy, runPipeline } = useClassificationRun();
  const [query, setQuery] = useState("");

  // 사용자용 테마 — 기본은 화이트(가독성 피드백), 네온은 토글로
  const [uiTheme, setUiTheme] = useState(
    () => window.localStorage.getItem("asap-user-theme") || "light",
  );
  useEffect(() => {
    window.localStorage.setItem("asap-user-theme", uiTheme);
    document.body.classList.remove("asap-cjs-neon", "consumer-body", "asap-user-light");
    if (uiTheme === "neon") {
      document.body.classList.add("asap-cjs-neon", "consumer-body");
    } else {
      document.body.classList.add("asap-user-light");
    }
    return () => document.body.classList.remove("asap-cjs-neon", "consumer-body", "asap-user-light");
  }, [uiTheme]);

  const start = () => {
    const text = clean(query);
    if (!text || busy) {
      return;
    }
    const isUrl = /^https?:\/\//i.test(text);
    runPipeline("full", {
      productName: isUrl ? "" : text,
      url: isUrl ? text : "",
      description: "",
    });
  };

  const status = clean(result?.job_status).toLowerCase();
  const completed = ["completed", "complete", "done"].includes(status);
  const failed = status === "failed" || !!result?.error;
  const candidates = asList(asObject(result?.candidate_code_set).candidates);
  const primary = candidates.find((c) => c.llm_recommended) || candidates[0] || null;
  const noCandidates = completed && !candidates.length;
  const stepIndex = consumerStepIndex(result);
  const jobId = clean(result?.job_id);

  return (
    <div className={`consumer theme-${uiTheme}`}>
      <div className="user-theme-toggle" role="group" aria-label="테마 선택">
        <button type="button" className={uiTheme === "light" ? "on" : ""} onClick={() => setUiTheme("light")}>화이트</button>
        <button type="button" className={uiTheme === "neon" ? "on" : ""} onClick={() => setUiTheme("neon")}>네온</button>
      </div>
      <div className="consumer-brand">
        <div className="consumer-logo-fire">
          {/* Trapcode(AE) 렌더 에셋 슬롯: webapp/src/assets/logo-fire.webm(알파 포함)이
              생기면 이 자리에 <video autoPlay loop muted playsInline>으로 교체 배선. */}
          <span
            className="consumer-logo-img"
            role="img"
            aria-label="ASAP"
            style={{ WebkitMaskImage: `url(${logo})`, maskImage: `url(${logo})` }}
          />
          <span className="consumer-embers" aria-hidden="true">
            <i /><i /><i /><i /><i /><i />
          </span>
        </div>
        <p>상품 링크 하나로 EU 수출 관세 코드를 찾아드립니다</p>
      </div>

      <div className="consumer-input-card">
        <input
          className="consumer-input"
          placeholder="상품 URL 또는 상품명을 입력하세요"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && start()}
          disabled={busy}
        />
        <button type="button" className="consumer-go" onClick={start} disabled={busy}>
          {busy ? "분류 중…" : "분류 시작"}
        </button>
      </div>

      {busy ? (
        <div className="consumer-steps">
          {CONSUMER_STEPS.map((label, index) => (
            <div
              key={label}
              className={`consumer-step ${index < stepIndex ? "done" : index === stepIndex ? "now" : ""}`}
            >
              <span className="consumer-sdot" />
              {label}
            </div>
          ))}
        </div>
      ) : null}

      {failed ? (
        <div className="consumer-result">
          <div className="consumer-rlabel">분류를 완료하지 못했어요</div>
          <p className="consumer-rdesc">{clean(result?.error) || "잠시 후 다시 시도해주세요."}</p>
        </div>
      ) : null}

      {noCandidates ? (
        <div className="consumer-result">
          <div className="consumer-rlabel">코드를 확정하지 못했어요</div>
          <p className="consumer-rdesc">
            상품 정보가 부족합니다. 상품 상세 페이지 URL로 다시 시도하면 정확도가 올라갑니다.
          </p>
        </div>
      ) : null}

      {completed && primary ? (
        <div className="consumer-result">
          <div className="consumer-rlabel">추천 관세 코드 · CN8</div>
          <div className="consumer-candidate-list">
            <article className="consumer-candidate recommended">
              <div className="consumer-candidate-topline">
                <strong>추천</strong>
              </div>
              <div className="consumer-code">{formatCode(primary.cn8)}</div>
              <div className="consumer-taric-label">
                TARIC10 {taricChoices(primary).length === 1 ? taricChoices(primary)[0] : taricChoices(primary).length ? `${taricChoices(primary).length}개 후보` : "확인 중"}
              </div>
              <CandidateDocuments candidate={primary} jobId={jobId} />
              {asList(primary.similar_ebti_cases).length ? (
                <details className="consumer-precedents">
                  <summary>유사 EU 분류 판례 {asList(primary.similar_ebti_cases).length}건 참고</summary>
                  {asList(primary.similar_ebti_cases).map((item, index) => (
                    <div className="consumer-precedent" key={index}>
                      <div className="consumer-precedent-ref">{clean(item.evidence_ref)}</div>
                      {clean(item.case_summary) ? <div className="consumer-precedent-body">{clean(item.case_summary)}</div> : null}
                      <div className="consumer-precedent-sim">{clean(item.similarity_comment)}</div>
                    </div>
                  ))}
                </details>
              ) : null}
            </article>
          </div>
          <div className="consumer-why"><Link to="/classification">분류 근거 전체 보기 ›</Link></div>
        </div>
      ) : null}
    </div>
  );
}
