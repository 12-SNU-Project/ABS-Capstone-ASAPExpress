import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useClassificationRun } from "../hooks/useClassificationRun";
import { useBlackboardTrace } from "../hooks/useBlackboardTrace";
import { EBTI_CONSULT_URL, buildConsumerWhy, summarizeSummons } from "../lib/traceContract.js";
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

export default function ConsumerPage() {
  const { result, busy, runPipeline } = useClassificationRun();
  const [query, setQuery] = useState("");
  const [altIndex, setAltIndex] = useState(-1);

  // 새 run이 뜨면 판례 선택을 추천 코드로 리셋
  useEffect(() => {
    setAltIndex(-1);
  }, [result?.job_id]);

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
  const alternates = candidates.filter((c) => c !== primary).slice(0, 2);
  const basis = clean(asList(primary?.classification_basis)[0]);
  // 판례는 선택된 후보 기준 — 기본은 추천 코드, 대안 칩을 누르면 그 코드의 판례
  const shownCandidate =
    altIndex >= 0 && alternates[altIndex] ? alternates[altIndex] : primary;
  const precedents = asList(shownCandidate?.similar_ebti_cases);
  const noCandidates = completed && !candidates.length;
  const stepIndex = consumerStepIndex(result);

  // 기록 의무화 trace — "왜 이 코드인가" 3줄 (정체/상태·형태/판례)
  const trace = useBlackboardTrace(result?.job_id, completed);
  const why = buildConsumerWhy(trace, shownCandidate?.cn8);
  const summonsRows = summarizeSummons(trace?.summons);

  const copyRefs = () => {
    try {
      navigator.clipboard?.writeText(why.refs.join(", "));
    } catch {
      /* clipboard unavailable */
    }
  };

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
          <div className="consumer-code">{formatCode(primary.cn8)}</div>
          <div className="consumer-conf">
            ● {primary.llm_recommended ? "신뢰도 높음" : "후보 검토 권장"}
          </div>
          {alternates.length ? (
            <>
              <div className="consumer-alts">
                {alternates.map((candidate, index) => (
                  <button
                    type="button"
                    className={`consumer-alt ${altIndex === index ? "active" : ""}`}
                    key={index}
                    onClick={() => setAltIndex(altIndex === index ? -1 : index)}
                  >
                    {formatCode(candidate.cn8)}
                  </button>
                ))}
              </div>
              <div className="consumer-alt-hint">후보 코드를 누르면 해당 코드의 판례를 볼 수 있어요</div>
            </>
          ) : null}
          <div className="consumer-why">
            {why.lines.length ? (
              <div className="consumer-why-lines">
                <b>왜 이 코드인가</b>
                {why.lines.map((line) => (
                  <div className={`consumer-why-line k-${line.kind}`} key={line.kind}>
                    {line.text}
                    {line.kind === "precedent" && line.refs?.length ? (
                      <span className="consumer-why-refs">
                        {line.refs.slice(0, 3).map((ref) => (
                          <em key={ref}>{ref}</em>
                        ))}
                        <button type="button" onClick={copyRefs} title="판례 번호 복사">복사</button>
                        <a href={EBTI_CONSULT_URL} target="_blank" rel="noreferrer" title="EU EBTI 공개 DB에서 번호로 조회">
                          EBTI 조회 ↗
                        </a>
                      </span>
                    ) : null}
                  </div>
                ))}
                {why.refs.length ? (
                  <div className="consumer-why-note">판례는 참고 근거(2급)이며 확정 사유가 아닙니다.</div>
                ) : null}
              </div>
            ) : basis ? (
              <>{basis.slice(0, 120)} </>
            ) : (
              "분류 근거와 서류 연결은 상세 화면에서 확인할 수 있습니다. "
            )}
            {summonsRows.length ? (
              <div className="consumer-summons">
                {summonsRows.slice(0, 1).map((row, index) => (
                  <span key={index}>
                    {row.fired
                      ? `판례 발동: ${row.code}`
                      : `판례 조회: ${row.reviewed || "-"}건 검토 — ${row.silenceLabel || "미반영"}`}
                  </span>
                ))}
              </div>
            ) : null}
            <Link to="/classification">자세히 보기 ›</Link>
            {precedents.length ? (
              <details className="consumer-precedents" open={altIndex >= 0}>
                <summary>
                  유사 EU 분류 판례 {precedents.length}건 참고
                  {altIndex >= 0 ? ` (${formatCode(shownCandidate?.cn8)} 기준)` : ""} ›
                </summary>
                {precedents.map((item, index) => (
                  <div className="consumer-precedent" key={index}>
                    <div className="consumer-precedent-ref">{clean(item.evidence_ref)}</div>
                    {clean(item.case_summary) ? (
                      <div className="consumer-precedent-body">{clean(item.case_summary)}</div>
                    ) : null}
                    <div className="consumer-precedent-sim">{clean(item.similarity_comment)}</div>
                  </div>
                ))}
              </details>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
