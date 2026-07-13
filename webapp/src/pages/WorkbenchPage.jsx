import { useEffect, useMemo, useState } from "react";
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
  UNDERSTANDING_KEYS,
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

function StageRail({ result, derived }) {
  const info = currentStageInfo(result);
  const completed = STAGES.filter(([key]) => stageState(result, derived, key) === "done").length;
  return (
    <div id="cjs-stage-rail" className="cjs-stage-rail">
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

function ProductPanel({ result }) {
  const inputView = asObject(result?.input_processing_view);
  const understandingView = asObject(result?.product_understanding_view);
  const understanding = { ...understandingView, ...asObject(understandingView.identity_hints) };
  const reconstructedFacts = asList(inputView.reconstructed_product_facts);
  const composition = asObject(understandingView.composition_facts);
  const compositionRows = parseCompositionTerms(composition.composition_terms);
  const percentages = asList(composition.ingredient_percentages);
  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">상품 이해 결과</div>
      <div className="cjs-understanding-grid">
        <div>
          <KeyValueRows data={asObject(inputView.page_product_facts)} keys={PRODUCT_FACT_KEYS} limit={6} />
          <div className="cjs-subpanel-title">입력 복원</div>
          <KeyValueRows data={asObject(inputView.reconstruction_status)} keys={RECONSTRUCTION_KEYS} limit={8} />
          <div className="cjs-subpanel-title">분류에 사용한 상품 정보</div>
          <KeyValueRows data={understanding} keys={UNDERSTANDING_KEYS} limit={14} />
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
          <div className="cjs-subpanel-title">Composition lane</div>
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

function RoutingPanel({ result }) {
  const routingView = asObject(result?.routing_view);
  const chapterDetails = asList(routingView.candidate_chapter_details);
  return (
    <div className="cjs-panel">
      <div className="cjs-panel-title">챕터 분기</div>
      <KeyValueRows
        data={routingView}
        keys={ROUTE_KEYS.filter((key) => key !== "candidate_chapter_details")}
        limit={10}
      />
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
  const derived = useWorkbenchDerived(result);

  useEffect(() => {
    document.body.classList.toggle("asap-cjs-neon", theme === "neon");
    document.body.classList.toggle("asap-cjs-classic", theme !== "neon");
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    return () => {
      document.body.classList.remove("asap-cjs-neon", "asap-cjs-classic");
    };
  }, [theme]);

  const selectedCandidate =
    derived.candidates.find(
      (candidate, index) => candidateKey(candidate, index) === selectedKey,
    ) || derived.candidates[0] || null;

  const setField = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  return (
    <div className={`classification-js-shell theme-${theme === "neon" ? "neon" : "classic"}`}>
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
          <div className="cjs-runtime-status">
            <span>API {import.meta.env.VITE_API_BASE_URL || "(proxy)"}</span>
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

      <section className="cjs-workspace">
        <StageRail result={result} derived={derived} />
        <main className="cjs-main-column">
          <DecisionPanel result={result} derived={derived} />
          <CandidateBoard derived={derived} selectedKey={selectedKey} onSelect={setSelectedKey} />
          <TaricPanel result={result} derived={derived} candidate={selectedCandidate} />
        </main>
        <aside className="cjs-inspector">
          <RoutingPanel result={result} />
          <TracePanel candidate={selectedCandidate} />
        </aside>
      </section>

      {/* 표(복원 fact / composition lane)가 있어 전체 폭 섹션으로 배치 */}
      <section className="cjs-understanding-section">
        <ProductPanel result={result} />
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
