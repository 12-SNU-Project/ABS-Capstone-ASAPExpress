import { candidateKey, sourceLabel } from "@/lib/format.js";

export default function TariffCandidateList({ candidates, selectedKey, onSelect }) {
  if (!candidates.length) {
    return (
      <div className="cjs-candidate-board">
        <div className="cjs-panel-title">CN8(8자리) 분류 후보</div>
        <div className="cjs-muted">분류 후보가 여기에 표시됩니다.</div>
      </div>
    );
  }
  const defaultIndex = Math.max(candidates.findIndex((candidate) => candidate.llm_recommended), 0);
  const activeKey = candidates.some((candidate, index) => candidateKey(candidate, index) === selectedKey)
    ? selectedKey
    : candidateKey(candidates[defaultIndex], defaultIndex);

  return (
    <div className="cjs-candidate-board">
      <div className="cjs-candidate-heading">
        <div>
          <div className="cjs-panel-title">CN8(8자리) 분류 후보</div>
          <small>후보를 선택하면 바로 아래 결정 근거가 해당 코드 기준으로 바뀝니다.</small>
        </div>
        <strong>{candidates.length}건</strong>
      </div>
      <div className="cjs-candidate-grid">
        {candidates.map((candidate, index) => {
          const key = candidateKey(candidate, index);
          return (
            <button
              type="button"
              key={key}
              className={`cjs-candidate-card ${key === activeKey ? "active" : ""}`}
              aria-pressed={key === activeKey}
              onClick={() => onSelect(key)}
            >
              <span className="cjs-rank">{candidate.rank || index + 1}순위</span>
              <span className="cjs-source">
                {sourceLabel(candidate.candidate_source || candidate.status || "candidate")}
              </span>
              <div className="cjs-code-row"><span>HS6</span><strong>{candidate.hs6 || "-"}</strong></div>
              <div className="cjs-code-row"><span>CN8</span><strong>{candidate.cn8 || "-"}</strong></div>
              <div className="cjs-card-foot">
                {candidate.llm_recommended ? "현재 1순위 후보" : "검토 후보"}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
