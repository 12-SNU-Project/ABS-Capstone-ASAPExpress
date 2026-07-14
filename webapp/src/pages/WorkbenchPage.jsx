import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import DataTable from "../components/DataTable";
import KeyValueRows from "../components/KeyValueRows";
import { useClassificationRun } from "../hooks/useClassificationRun";
import {
  EVENT_STAGE_LABELS,
  PRODUCT_FACT_KEYS,
  RECONSTRUCTION_KEYS,
  ROUTE_KEYS,
  STAGES,
} from "../lib/labels.js";
import {
  asList,
  asObject,
  candidateKey,
  clean,
  sourceLabel,
  statusLabel,
} from "../lib/format.js";

const THEME_STORAGE_KEY = "asap-classification-theme";

function eventLabel(stage) {
  const key = clean(stage);
  return EVENT_STAGE_LABELS[key] || key || "대기";
}

function componentDone(result, nameFragment) {
  return asList(result?.component_results).some(
    (entry) =>
      clean(entry.component_name).toLowerCase().includes(nameFragment) && entry.success,
  );
}

function eventStatus(result, stageNames) {
  let status = "idle";
  asList(result?.events).forEach((event) => {
    if (stageNames.includes(clean(event.stage))) {
      status = clean(event.status) || status;
    }
  });
  return status;
}

function useWorkbenchDerived(result) {
  return useMemo(() => {
    const candidateSet = asObject(result?.candidate_code_set);
    const candidates = asList(candidateSet.candidates);
    const hasTaricBranches = candidates.some(
      (candidate) => asList(candidate.taric10_branch_candidates).length > 0,
    );
    const packages = asList(result?.document_packages).slice();
    if (result?.document_package && typeof result.document_package === "object") {
      packages.push(result.document_package);
    }
    const packagesByTaric = {};
    packages.forEach((pkg) => {
      const taric = clean(pkg.taric10);
      if (taric) {
        (packagesByTaric[taric] = packagesByTaric[taric] || []).push(pkg);
      }
    });
    return { candidateSet, candidates, hasTaricBranches, packagesByTaric };
  }, [result]);
}

function stageState(result, derived, key) {
  if (key === "input") {
    return result?.input_processing_view
      ? "done"
      : eventStatus(result, ["Input_Intake", "Evidence_Intake_Component", "Product_Intake"]);
  }
  if (key === "understanding") {
    return result?.product_understanding_view || componentDone(result, "product_understanding")
      ? "done"
      : eventStatus(result, [
          "Product_Understanding_Component",
          "Product_Understanding",
          "ProductUnderstanding",
        ]);
  }
  if (key === "routing") {
    return result?.routing_view || componentDone(result, "hs2_routing")
      ? "done"
      : eventStatus(result, [
          "HS2_Routing_Component",
          "Regulatory_Domain_Routing",
          "Domain_Router",
          "Regulatory_Domain",
        ]);
  }
  if (key === "classification") {
    return derived.candidates.length
      ? "done"
      : eventStatus(result, ["Classification", "Classification_Component"]);
  }
  if (key === "taric") {
    return derived.hasTaricBranches ? "done" : derived.candidates.length ? "running" : "idle";
  }
  if (key === "document") {
    return asList(result?.document_packages).length || result?.document_package
      ? "done"
      : derived.hasTaricBranches
        ? "running"
        : "idle";
  }
  return "idle";
}

function currentStageInfo(result) {
  const events = asList(result?.events);
  const lastRelevant =
    events
      .slice()
      .reverse()
      .find((event) => clean(event.stage) && clean(event.stage) !== "Pipeline") ||
    events[events.length - 1] ||
    null;
  const status = clean(result?.job_status || lastRelevant?.status || "idle");
  if (result?.error) {
    return { label: "오류", status: "failed", message: result.error };
  }
  if (status === "completed" || status === "complete") {
    return {
      label: "전체 완료",
      status: "completed",
      message: "분류 결과와 서류 연결 정보를 확인할 수 있습니다.",
    };
  }
  if (!lastRelevant) {
    return {
      label: "대기",
      status: "idle",
      message: "상품명 또는 URL을 입력하고 분류를 실행하세요.",
    };
  }
  return {
    label: eventLabel(lastRelevant.stage),
    status: clean(lastRelevant.status || status || "running"),
    message: clean(lastRelevant.message) || "처리 중입니다.",
  };
}

function StageNav({ result, derived, activeStage, onSelect, busy }) {
  const info = currentStageInfo(result);
  const completed = STAGES.filter(([key]) => stageState(result, derived, key) === "done").length;
  return (
    <div id="cjs-stage-rail" className={`cjs-stage-rail ${busy ? "busy" : ""}`}>
      <div className="cjs-panel-title">진행 상황</div>
      <div className={`cjs-current-stage ${info.status}`}>
        <span className="cjs-stage-dot" />
        <div>
          <strong>{info.label}</strong>
          <small>
            {statusLabel(info.status)} · {completed}/{STAGES.length}
          </small>
          <p>{info.message}</p>
        </div>
      </div>
      {busy ? (
        <div className="cjs-progressbar" aria-hidden="true">
          <span />
        </div>
      ) : null}
      <nav className="cjs-stage-nav">
        {STAGES.map(([key, label]) => {
          const state = stageState(result, derived, key);
          return (
            <button
              key={key}
              type="button"
              className={`cjs-stage-item ${activeStage === key ? "active" : ""} state-${state}`}
              onClick={() => onSelect(key)}
            >
              <span className="cjs-stage-item-dot" />
              {label}
            </button>
          );
        })}
      </nav>
    </div>
  );
}

function DecisionPanel({ result, derived }) {
  const { candidateSet, candidates } = derived;
  const primary = candidates.find((candidate) => candidate.llm_recommended) || candidates[0] || {};
  const note =
    candidateSet.classification_status ||
    candidateSet.failure_reason ||
    result?.error ||
    "분류 실행을 기다리고 있습니다.";
  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">분류 결론</div>
      <div className="cjs-metric-grid">
        <div>
          <span>작업 번호</span>
          <strong>{result?.job_id || "-"}</strong>
        </div>
        <div>
          <span>진행 상태</span>
          <strong>{statusLabel(result?.job_status || "idle")}</strong>
        </div>
        <div>
          <span>후보 수</span>
          <strong>{candidates.length}</strong>
        </div>
        <div>
          <span>추천 CN8</span>
          <strong>{primary.cn8 || "-"}</strong>
        </div>
      </div>
      <div className={`cjs-note ${result?.error ? "error" : ""}`}>{note}</div>
    </div>
  );
}

function CandidateBoard({ derived, selectedKey, onSelect }) {
  const { candidates } = derived;
  if (!candidates.length) {
    return (
      <div className="cjs-candidate-board">
        <div className="cjs-panel">
          <div className="cjs-panel-title">분류 후보</div>
          <div className="cjs-muted">분류 후보가 여기에 표시됩니다.</div>
        </div>
      </div>
    );
  }
  const activeKey = selectedKey || candidateKey(candidates[0], 0);
  return (
    <div className="cjs-candidate-board">
      <div className="cjs-panel-title">분류 후보</div>
      <div className="cjs-candidate-grid">
        {candidates.map((candidate, index) => {
          const key = candidateKey(candidate, index);
          const branches = asList(candidate.taric10_branch_candidates);
          return (
            <button
              type="button"
              key={key}
              className={`cjs-candidate-card ${key === activeKey ? "active" : ""}`}
              onClick={() => onSelect(key)}
            >
              <span className="cjs-rank">{candidate.rank || index + 1}순위</span>
              <span className="cjs-source">
                {sourceLabel(candidate.candidate_source || candidate.status || "candidate")}
              </span>
              <div className="cjs-code-row">
                <span>HS6</span>
                <strong>{candidate.hs6 || "-"}</strong>
              </div>
              <div className="cjs-code-row">
                <span>CN8</span>
                <strong>{candidate.cn8 || "-"}</strong>
              </div>
              <div className="cjs-code-row">
                <span>TARIC</span>
                <strong>{candidate.taric10 || "-"}</strong>
              </div>
              <div className="cjs-card-foot">
                TARIC10 후보 {branches.length || candidate.taric10_branch_count || 0}개 ·{" "}
                {candidate.llm_recommended ? "최종 추천" : "후보 유지"}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function TaricPanel({ result, derived, candidate }) {
  if (!candidate) {
    return (
      <div className="cjs-panel">
        <div className="cjs-panel-title">TARIC10 후보</div>
        <div className="cjs-muted">후보를 선택하면 CN8 아래의 TARIC10 후보가 표시됩니다.</div>
      </div>
    );
  }
  const jobId = clean(result?.job_id || result?.run_id);
  const branches = asList(candidate.taric10_branch_candidates);
  const rows = branches.length ? branches : [{ taric10: candidate.taric10 }];
  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">TARIC10 후보</div>
      <div className="cjs-note">
        CN8 {candidate.cn8 || "-"} 아래 신고 가능한 TARIC10 후보를 유지합니다.
      </div>
      <div className="cjs-taric-list">
        {rows.map((branch, index) => {
          const taric = clean(branch.taric10 || branch.code || branch);
          const linked = asList(derived.packagesByTaric[taric]).length > 0;
          if (!jobId || !taric) {
            return (
              <span key={`${taric}_${index}`} className="cjs-taric-row">
                <strong>{taric || "-"}</strong>
                <span>서류 연결 대기</span>
              </span>
            );
          }
          return (
            <Link
              key={`${taric}_${index}`}
              className={`cjs-taric-row ${linked ? "linked" : ""}`}
              to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(taric)}`}
            >
              <strong>{taric || "-"}</strong>
              <span>{linked ? "서류 패키지 보기" : "서류 연결 대기"}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

// composition_terms는 "키: 값" 문자열 목록 — LLM reconstruction 표의 행이다.
function parseCompositionTerms(terms) {
  return asList(terms)
    .map((term) => {
      const text = clean(term);
      const splitAt = text.indexOf(":");
      if (splitAt < 1) {
        return { 구분: "", 내용: text };
      }
      return { 구분: text.slice(0, splitAt).trim(), 내용: text.slice(splitAt + 1).trim() };
    })
    .filter((row) => row.내용);
}

function IntakePanel({ result }) {
  const inputView = asObject(result?.input_processing_view);
  const reconstructedFacts = asList(inputView.reconstructed_product_facts);
  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">입력 · LLM 복원</div>
      <div className="cjs-understanding-grid">
        <div>
          <KeyValueRows data={asObject(inputView.page_product_facts)} keys={PRODUCT_FACT_KEYS} limit={6} />
          <div className="cjs-subpanel-title">입력 복원 상태</div>
          <KeyValueRows data={asObject(inputView.reconstruction_status)} keys={RECONSTRUCTION_KEYS} limit={8} />
        </div>
        <div>
          <div className="cjs-subpanel-title cjs-first">복원 fact 표 ({reconstructedFacts.length}건)</div>
          <DataTable
            rows={reconstructedFacts}
            limit={30}
            emptyMessage="LLM 복원이 만든 구조화 fact가 없습니다."
            columns={[
              { key: "field_name", label: "필드", variant: "mono" },
              { key: "normalized_value", label: "값" },
              { key: "source_refs", label: "출처", variant: "mono" },
              { key: "validation_status", label: "상태", variant: "pill" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function CoiEvidenceBlock({ coi }) {
  const evidence = asObject(coi);
  const documents = asList(evidence.matched_documents);
  const texts = asList(evidence.matched_texts);
  const scores = asList(evidence.match_scores);
  const rows = texts.map((text, index) => ({
    문서: clean(documents[index] || documents[0] || "-"),
    "매칭 텍스트": clean(text),
    점수: scores[index] !== undefined ? scores[index] : "",
  }));
  return (
    <>
      <div className="cjs-subpanel-title">COI 보조 근거 ({rows.length}건)</div>
      {rows.length ? (
        <DataTable
          rows={rows}
          limit={8}
          columns={[
            { key: "문서", label: "문서", variant: "mono" },
            { key: "매칭 텍스트", label: "매칭 텍스트" },
            { key: "점수", label: "점수", variant: "mono" },
          ]}
        />
      ) : (
        <div className="cjs-muted">
          {clean(evidence.error) ? `COI 조회 오류: ${clean(evidence.error)}` : "매칭된 COI 근거가 없습니다."}
        </div>
      )}
    </>
  );
}

function PrecedentList({ cases }) {
  const list = asList(cases);
  if (!list.length) {
    return <div className="cjs-muted">이 후보와 연결된 유사 판례가 없습니다.</div>;
  }
  return (
    <div className="cjs-precedent-list">
      {list.map((item, index) => (
        <div className="cjs-precedent" key={index}>
          <div className="cjs-precedent-ref">{clean(item.evidence_ref)}</div>
          {clean(item.case_summary) ? (
            <div className="cjs-precedent-body">{clean(item.case_summary)}</div>
          ) : null}
          <div className="cjs-precedent-sim">{clean(item.similarity_comment)}</div>
          {clean(item.difference_comment) ? (
            <div className="cjs-precedent-diff">{clean(item.difference_comment)}</div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function TermChips({ label, terms }) {
  const list = asList(terms).map((term) => clean(term)).filter(Boolean);
  if (!list.length) {
    return null;
  }
  return (
    <div className="cjs-term-group">
      <div className="cjs-subpanel-title">{label} ({list.length})</div>
      <div className="cjs-chip-row">
        {list.slice(0, 16).map((term, index) => (
          <span className="cjs-chip" key={index}>
            {term}
          </span>
        ))}
      </div>
    </div>
  );
}

function UnderstandingPanel({ result }) {
  const understandingView = asObject(result?.product_understanding_view);
  const hints = asObject(understandingView.identity_hints);
  const composition = asObject(understandingView.composition_facts);
  const compositionRows = parseCompositionTerms(composition.composition_terms);
  const percentages = asList(composition.ingredient_percentages);
  const modeLabel = { llm_json: "LLM 분석", llm_fallback: "규칙 기반(대체)", regex_fallback: "규칙 기반" }[
    clean(hints.understanding_mode)
  ] || clean(hints.understanding_mode);
  const tiles = [
    ["영문 상품명", hints.translated_product_name],
    ["상업적 식별명", hints.commercial_identity],
    ["원재료 분류", hints.ingredient_class],
    ["식품 형태", hints.food_form],
    ["가공 상태", hints.processing_state],
    ["이해 방식", modeLabel],
    ["신뢰도", hints.confidence],
  ].filter(([, value]) => clean(value) !== "");
  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">상품 이해 결과</div>
      {tiles.length ? (
        <div className="cjs-fact-tiles">
          {tiles.map(([label, value]) => (
            <div className="cjs-fact-tile" key={label}>
              <span>{label}</span>
              <strong>{clean(value)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <div className="cjs-muted">상품 이해 결과가 아직 없습니다.</div>
      )}
      <div className="cjs-understanding-grid">
        <div>
          {clean(hints.normalized_tariff_description) ? (
            <>
              <div className="cjs-subpanel-title cjs-first">정규화 tariff 설명</div>
              <p className="cjs-desc-text">{clean(hints.normalized_tariff_description)}</p>
            </>
          ) : null}
          <TermChips label="식별 토큰" terms={hints.identity_terms} />
          <TermChips label="형태 토큰" terms={hints.product_form_terms} />
          <TermChips label="챕터 힌트" terms={hints.chapter_hint_terms} />
          <TermChips label="라우팅 토큰" terms={understandingView.routing_terms} />
          <CoiEvidenceBlock coi={understandingView.coi_evidence} />
        </div>
        <div>
          <div className="cjs-subpanel-title cjs-first">Composition lane</div>
          <div className="cjs-chip-row">
            {clean(composition.processing_state) && composition.processing_state !== "unknown" ? (
              <span className="cjs-chip">가공: {composition.processing_state}</span>
            ) : null}
            {clean(composition.principal_ingredient) ? (
              <span className="cjs-chip">주원료: {composition.principal_ingredient}</span>
            ) : null}
            <span className="cjs-chip">함량 {percentages.length}건</span>
            {composition.contains_wrapper_or_dough ? <span className="cjs-chip">피/반죽 포함</span> : null}
            {composition.contains_sauce_or_broth ? <span className="cjs-chip">소스/육수 포함</span> : null}
          </div>
          <DataTable
            rows={compositionRows}
            limit={20}
            emptyMessage="composition lane에 반영된 항목이 없습니다."
            columns={[
              { key: "구분", label: "구분", variant: "mono" },
              { key: "내용", label: "내용" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function DocumentStagePanel({ result, derived }) {
  const jobId = clean(result?.job_id || result?.run_id);
  const packages = Object.entries(derived.packagesByTaric);
  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">서류 패키지 ({packages.length}건)</div>
      {packages.length ? (
        <div className="cjs-taric-list">
          {packages.map(([taric, group]) => (
            <Link
              key={taric}
              className="cjs-taric-row linked"
              to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(taric)}`}
            >
              <strong>{taric}</strong>
              <span>{asList(group).length}개 패키지 · 서류 추천 보기</span>
            </Link>
          ))}
        </div>
      ) : (
        <div className="cjs-muted">생성된 서류 패키지가 없습니다.</div>
      )}
    </div>
  );
}

function RoutingPanel({ result }) {
  const routingView = asObject(result?.routing_view);
  const chapterDetails = asList(routingView.candidate_chapter_details);
  const matchedTerms = asList(asObject(routingView.routing_basis).matched_terms);
  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">챕터 분기</div>
      <KeyValueRows
        data={routingView}
        keys={ROUTE_KEYS.filter(
          (key) => !["candidate_chapter_details", "routing_basis"].includes(key),
        )}
        limit={10}
      />
      <TermChips label="매칭 키워드" terms={matchedTerms} />
      {chapterDetails.length ? (
        <>
          <div className="cjs-subpanel-title">챕터 점수 상세</div>
          <DataTable rows={chapterDetails} limit={8} />
        </>
      ) : null}
    </div>
  );
}

function TracePanel({ candidate }) {
  const tree = asObject(candidate?.candidate_static_tree);
  const score = asObject(candidate?.score_breakdown);
  const basis = asList(candidate?.classification_basis).slice(0, 6);
  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">단계별 분류 근거</div>
      <div className="cjs-subpanel-title">코드 경로</div>
      <KeyValueRows data={tree} limit={8} />
      <div className="cjs-subpanel-title">점수 근거</div>
      <KeyValueRows data={score} limit={8} />
      <div className="cjs-subpanel-title">판단 메모</div>
      {basis.length ? (
        basis.map((line, index) => (
          <div className="cjs-pill" key={index}>
            {line}
          </div>
        ))
      ) : (
        <div className="cjs-muted">표시할 판단 메모가 없습니다.</div>
      )}
      <div className="cjs-subpanel-title">
        유사 EU 분류 판례 ({asList(candidate?.similar_ebti_cases).length}건)
      </div>
      <PrecedentList cases={candidate?.similar_ebti_cases} />
    </div>
  );
}

export default function WorkbenchPage() {
  const { result, busy, runPipeline } = useClassificationRun();
  const [form, setForm] = useState({ productName: "", url: "", description: "" });
  const [selectedKey, setSelectedKey] = useState("");
  const [theme, setTheme] = useState(
    () => window.localStorage.getItem(THEME_STORAGE_KEY) || "classic",
  );
  const [fx, setFx] = useState(
    () => window.localStorage.getItem("asap-classification-fx") || "calm",
  );
  useEffect(() => {
    window.localStorage.setItem("asap-classification-fx", fx);
  }, [fx]);
  const derived = useWorkbenchDerived(result);
  const [activeStage, setActiveStage] = useState("classification");
  const followStageRef = useRef(true);

  useEffect(() => {
    document.body.classList.toggle("asap-cjs-neon", theme === "neon");
    document.body.classList.toggle("asap-cjs-classic", theme !== "neon");
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    return () => {
      document.body.classList.remove("asap-cjs-neon", "asap-cjs-classic");
    };
  }, [theme]);

  // 실행 중에는 진행 단계를 자동 추적, 완료되면 분류 결과로 착지.
  // 사용자가 레일을 직접 클릭하면 그 run이 끝날 때까지 수동 모드 유지.
  useEffect(() => {
    if (busy) {
      followStageRef.current = true;
    }
  }, [busy]);

  useEffect(() => {
    if (!followStageRef.current) {
      return;
    }
    const status = clean(result?.job_status).toLowerCase();
    if (["completed", "complete", "done"].includes(status)) {
      setActiveStage("classification");
      return;
    }
    let latest = "input";
    STAGES.forEach(([key]) => {
      const state = stageState(result, derived, key);
      if (state === "done" || state === "running" || state === "completed") {
        latest = key;
      }
    });
    setActiveStage(latest);
  }, [result, derived, busy]);

  const pickStage = (key) => {
    followStageRef.current = false;
    setActiveStage(key);
  };

  const selectedCandidate =
    derived.candidates.find(
      (candidate, index) => candidateKey(candidate, index) === selectedKey,
    ) || derived.candidates[0] || null;

  const setField = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  return (
    <div
      className={`classification-js-shell theme-${theme === "neon" ? "neon" : "classic"} ${
        fx === "storm" ? "fx-storm" : ""
      }`}
    >
      {/* feTurbulence 구름 포그 — 카드 뒤에서 떠다니는 노이즈 안개 (테마별 틴트) */}
      <svg width="0" height="0" aria-hidden="true" focusable="false" style={{ position: "absolute" }}>
        <filter id="cjs-fog-classic" x="-20%" y="-20%" width="140%" height="140%">
          <feTurbulence type="fractalNoise" baseFrequency="0.008 0.014" numOctaves="3" seed="11">
            <animate
              attributeName="baseFrequency"
              values="0.008 0.014;0.011 0.017;0.008 0.014"
              dur="12s"
              repeatCount="indefinite"
            />
          </feTurbulence>
          {/* 라이트 테마: 부드러운 라벤더-인디고, 성긴 구름 */}
          <feColorMatrix
            type="matrix"
            values="0 0 0 0 0.47  0 0 0 0 0.4  0 0 0 0 0.86  0 0 0.62 0 -0.24"
          />
          <feGaussianBlur stdDeviation="10" />
        </filter>
        {/* 폭풍 모드: 회색 연기 (불난 집 굴뚝 톤) */}
        <filter id="cjs-smoke-classic" x="-20%" y="-20%" width="140%" height="140%">
          <feTurbulence type="fractalNoise" baseFrequency="0.011 0.019" numOctaves="4" seed="23">
            <animate
              attributeName="baseFrequency"
              values="0.011 0.019;0.015 0.024;0.011 0.019"
              dur="8s"
              repeatCount="indefinite"
            />
          </feTurbulence>
          <feColorMatrix
            type="matrix"
            values="0 0 0 0 0.42  0 0 0 0 0.43  0 0 0 0 0.48  0 0 0.95 0 -0.22"
          />
          <feGaussianBlur stdDeviation="8" />
        </filter>
        <filter id="cjs-smoke-neon" x="-20%" y="-20%" width="140%" height="140%">
          <feTurbulence type="fractalNoise" baseFrequency="0.011 0.019" numOctaves="4" seed="29">
            <animate
              attributeName="baseFrequency"
              values="0.011 0.019;0.016 0.025;0.011 0.019"
              dur="8s"
              repeatCount="indefinite"
            />
          </feTurbulence>
          {/* 어두운 배경에서 네온 불빛에 비친 밝은 회백색 연기 */}
          <feColorMatrix
            type="matrix"
            values="0 0 0 0 0.78  0 0 0 0 0.77  0 0 0 0 0.84  0 0 0.9 0 -0.2"
          />
          <feGaussianBlur stdDeviation="8" />
        </filter>
        <filter id="cjs-fog-neon" x="-20%" y="-20%" width="140%" height="140%">
          <feTurbulence type="fractalNoise" baseFrequency="0.008 0.014" numOctaves="3" seed="7">
            <animate
              attributeName="baseFrequency"
              values="0.008 0.014;0.012 0.018;0.008 0.014"
              dur="12s"
              repeatCount="indefinite"
            />
          </feTurbulence>
          {/* 네온 테마: 밝은 바이올렛, 짙은 구름 */}
          <feColorMatrix
            type="matrix"
            values="0 0 0 0 0.68  0 0 0 0 0.36  0 0 0 0 0.99  0 0 0.85 0 -0.16"
          />
          <feGaussianBlur stdDeviation="9" />
        </filter>
      </svg>
      <div className="cjs-fog-layer" aria-hidden="true" />
      <div className="cjs-hero">
        <div className="cjs-heading">
          <div className="cjs-eyebrow">ASAP Classification</div>
          <h1 className="cjs-title">EU 수출 품목분류</h1>
          <div className="cjs-subtitle">
            상품 정보를 읽고 HS6/CN8 후보와 TARIC10 서류 연결 지점을 확인합니다.
          </div>
        </div>
        <div className="cjs-hero-tools">
          <div className="cjs-theme-toggle">
            <span className="cjs-theme-label">테마</span>
            <button
              type="button"
              className={`cjs-theme-button ${theme !== "neon" ? "active" : ""}`}
              onClick={() => setTheme("classic")}
            >
              기본
            </button>
            <button
              type="button"
              className={`cjs-theme-button ${theme === "neon" ? "active" : ""}`}
              onClick={() => setTheme("neon")}
            >
              네온
            </button>
          </div>
          <div className="cjs-theme-toggle">
            <span className="cjs-theme-label">이펙트</span>
            <button
              type="button"
              className={`cjs-theme-button ${fx !== "storm" ? "active" : ""}`}
              onClick={() => setFx("calm")}
            >
              은은
            </button>
            <button
              type="button"
              className={`cjs-theme-button ${fx === "storm" ? "active" : ""}`}
              onClick={() => setFx("storm")}
            >
              폭풍
            </button>
          </div>
          <div className="cjs-runtime-status">
            <strong>{statusLabel(result?.job_status || "idle")}</strong>
            {result?.error ? <em>{result.error}</em> : null}
          </div>
        </div>
      </div>

      <section className="cjs-run-card">
        <div className="cjs-field">
          <label htmlFor="cjs-product-name">상품명</label>
          <input
            id="cjs-product-name"
            type="text"
            className="cjs-input"
            placeholder="예: 신라면, 낙지 볶음, 데오도란트"
            value={form.productName}
            onChange={setField("productName")}
          />
        </div>
        <div className="cjs-field cjs-field-wide">
          <label htmlFor="cjs-product-url">상품 URL</label>
          <input
            id="cjs-product-url"
            type="text"
            className="cjs-input"
            placeholder="Kurly 또는 상품 상세 URL"
            value={form.url}
            onChange={setField("url")}
          />
        </div>
        <div className="cjs-field cjs-field-full">
          <label htmlFor="cjs-description">설명 / 추가 facts</label>
          <textarea
            id="cjs-description"
            className="cjs-textarea"
            placeholder="원재료, 형태, 가공 상태, 함량 조건 등을 필요하면 입력"
            value={form.description}
            onChange={setField("description")}
          />
        </div>
        <div className="cjs-run-actions">
          <button
            type="button"
            className="cjs-primary-button"
            disabled={busy}
            onClick={() => runPipeline("full", form)}
          >
            분류 실행
          </button>
          <button
            type="button"
            className="cjs-secondary-button"
            disabled={busy}
            onClick={() => runPipeline("cached", form)}
          >
            최근 입력으로 실행
          </button>
          <button
            type="button"
            className="cjs-secondary-button"
            disabled={busy}
            onClick={() => runPipeline("reconstruct", form)}
          >
            상품 정보만 복원
          </button>
        </div>
      </section>

      <section className="cjs-workspace cjs-workspace-nav">
        <StageNav
          result={result}
          derived={derived}
          activeStage={activeStage}
          onSelect={pickStage}
          busy={busy}
        />
        <main className="cjs-stage-content">
          {activeStage === "input" ? <IntakePanel result={result} /> : null}
          {activeStage === "understanding" ? <UnderstandingPanel result={result} /> : null}
          {activeStage === "routing" ? <RoutingPanel result={result} /> : null}
          {activeStage === "classification" ? (
            <>
              <DecisionPanel result={result} derived={derived} />
              <CandidateBoard derived={derived} selectedKey={selectedKey} onSelect={setSelectedKey} />
              <TracePanel candidate={selectedCandidate} />
            </>
          ) : null}
          {activeStage === "taric" ? (
            <>
              <CandidateBoard derived={derived} selectedKey={selectedKey} onSelect={setSelectedKey} />
              <TaricPanel result={result} derived={derived} candidate={selectedCandidate} />
            </>
          ) : null}
          {activeStage === "document" ? (
            <DocumentStagePanel result={result} derived={derived} />
          ) : null}
        </main>
      </section>

      <section className="cjs-debug-section">
        <details className="cjs-panel">
          <summary className="cjs-panel-title">상세 실행 로그</summary>
          <pre className="cjs-json-preview">{JSON.stringify(result || {}, null, 2)}</pre>
        </details>
      </section>
    </div>
  );
}
