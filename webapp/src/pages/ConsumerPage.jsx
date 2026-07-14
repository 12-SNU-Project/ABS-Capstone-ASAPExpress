import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useClassificationRun } from "../hooks/useClassificationRun";
import { asList, asObject, clean } from "../lib/format.js";

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

  // 네온 톤 통일: 톱바까지 어둡게
  useEffect(() => {
    document.body.classList.add("asap-cjs-neon", "consumer-body");
    return () => document.body.classList.remove("asap-cjs-neon", "consumer-body");
  }, []);

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
  const noCandidates = completed && !candidates.length;
  const stepIndex = consumerStepIndex(result);

  return (
    <div className="consumer">
      <div className="consumer-brand">
        <div className="consumer-logo">ASAP</div>
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
            <div className="consumer-alts">
              {alternates.map((candidate, index) => (
                <span className="consumer-alt" key={index}>
                  {formatCode(candidate.cn8)}
                </span>
              ))}
            </div>
          ) : null}
          <div className="consumer-why">
            {basis ? <>{basis.slice(0, 120)} </> : "분류 근거와 서류 연결은 상세 화면에서 확인할 수 있습니다. "}
            <Link to="/classification">자세히 보기 ›</Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}
