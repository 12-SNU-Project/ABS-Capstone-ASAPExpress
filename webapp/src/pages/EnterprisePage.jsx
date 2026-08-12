import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import logo from "../assets/asap_black.png";
import {
  fetchCases,
  reportDocStatus,
  submitDocRequest,
  uploadDocument,
} from "../lib/enterpriseApi.js";
import { asList, asObject, clean } from "../lib/format.js";
import { DocumentReasonLabel } from "../lib/labels.js";

const DOCUMENT_CATEGORY_LABELS = {
  product: "물품 서류",
  customs: "통관 서류",
  company: "기업 서류",
};

const DOCUMENT_STATUS = {
  verified: ["원본 확인", "ok"],
  unverified: ["확인 필요", "warn"],
  agency: ["대행 진행", "violet"],
  url_sent: ["수취 대기", "info"],
  missing: ["준비 필요", "miss"],
};

function DocumentIsActive(document) {
  const item = asObject(document);
  return !["", "missing"].includes(clean(item.quality));
}

function SelectedCasePanel({ caseData, onDocumentChange }) {
  const source = asObject(caseData);
  const documents = asList(source.documents);
  const activeDocuments = documents.filter(DocumentIsActive).length;
  const jobId = clean(source.lastJobId);
  const taric10 = clean(source.taric10);
  const caseId = clean(source.caseId);
  const fileInputRef = useRef(null);
  const fileTargetRef = useRef("");
  const [activeCategory, setActiveCategory] = useState("product");
  const [busyDocument, setBusyDocument] = useState("");
  const [requestDocument, setRequestDocument] = useState("");
  const [requestContact, setRequestContact] = useState("");
  const [actionError, setActionError] = useState("");
  const categoryCounts = Object.fromEntries(
    Object.keys(DOCUMENT_CATEGORY_LABELS).map((category) => [
      category,
      documents.filter((document) => clean(asObject(document).cat) === category).length,
    ]),
  );
  const availableCategories = Object.keys(DOCUMENT_CATEGORY_LABELS).filter(
    (category) => categoryCounts[category] > 0,
  );
  const visibleCategory = availableCategories.includes(activeCategory)
    ? activeCategory
    : availableCategories[0] || "product";
  const visibleDocuments = documents.filter(
    (document) => clean(asObject(document).cat) === visibleCategory,
  );

  const saveDocumentChange = async (documentKey, changes) => {
    if (!caseId || busyDocument) {
      return;
    }
    setBusyDocument(documentKey);
    setActionError("");
    try {
      await reportDocStatus({ caseId, doc: documentKey, ...changes });
      onDocumentChange(documentKey, changes);
    } catch (error) {
      setActionError(String(error?.message || error));
    } finally {
      setBusyDocument("");
    }
  };

  const chooseFile = (documentKey) => {
    fileTargetRef.current = documentKey;
    fileInputRef.current?.click();
  };

  const handleFile = async (event) => {
    const file = event.target.files?.[0];
    const documentKey = fileTargetRef.current;
    event.target.value = "";
    if (!file || !caseId || !documentKey || busyDocument) {
      return;
    }
    setBusyDocument(documentKey);
    setActionError("");
    try {
      const response = await uploadDocument(caseId, documentKey, file);
      onDocumentChange(documentKey, {
        quality: "unverified",
        file: clean(response?.file) || file.name,
        filePath: clean(response?.filePath),
        origin: "직접 업로드",
      });
    } catch (error) {
      setActionError(String(error?.message || error));
    } finally {
      setBusyDocument("");
    }
  };

  const recordDocumentRequest = async (documentKey) => {
    const contact = clean(requestContact);
    if (!caseId || !contact || busyDocument) {
      return;
    }
    setBusyDocument(documentKey);
    setActionError("");
    try {
      await submitDocRequest({ caseId, doc: documentKey, contact });
      onDocumentChange(documentKey, { requested: contact });
      setRequestDocument("");
      setRequestContact("");
    } catch (error) {
      setActionError(String(error?.message || error));
    } finally {
      setBusyDocument("");
    }
  };

  return (
    <section className="ent-card ent-project-detail">
      <div className="ent-card-title">
        선택 프로젝트
        <span className="ent-badge live">실데이터</span>
      </div>
      <div className="ent-project-summary">
        <div>
          <span>상품</span>
          <strong>{clean(source.name) || "상품명 미입력"}</strong>
          <small>{clean(source.url) || "상품 URL 미입력"}</small>
        </div>
        <div>
          <span>TARIC10</span>
          <strong className="ent-project-code">{taric10 || "미확정"}</strong>
          <small>{jobId ? `분류 작업 ${jobId}` : "연결된 분류 작업 없음"}</small>
        </div>
        <div>
          <span>서류 준비 현황</span>
          <strong>{activeDocuments} / {documents.length}</strong>
          <small>업로드·검토·수취가 시작된 항목</small>
        </div>
      </div>

      <div className="ent-project-doc-heading">
        <strong>서류 인벤토리</strong>
        <span>분류 결과에서 생성된 항목을 카테고리별로 관리합니다.</span>
      </div>
      <div className="ent-project-category-tabs" role="tablist" aria-label="서류 카테고리">
        {Object.entries(DOCUMENT_CATEGORY_LABELS).map(([category, label]) => {
          const count = categoryCounts[category];
          return (
            <button
              type="button"
              role="tab"
              aria-selected={visibleCategory === category}
              className={visibleCategory === category ? "active" : ""}
              key={category}
              disabled={!count}
              onClick={() => setActiveCategory(category)}
            >
              <span>{label}</span>
              <strong>{count}</strong>
            </button>
          );
        })}
      </div>
      <input ref={fileInputRef} className="ent-visually-hidden" type="file" onChange={handleFile} />
      {documents.length ? (
        <div className="ent-project-doc-list">
          {visibleDocuments.map((document, index) => {
            const item = asObject(document);
            const documentKey = clean(item.key) || `${clean(item.name)}-${index}`;
            const [status, tone] = clean(item.requested) && clean(item.quality) === "missing"
              ? ["요청 기록", "info"]
              : DOCUMENT_STATUS[clean(item.quality)] || DOCUMENT_STATUS.missing;
            const busy = busyDocument === documentKey;
            return (
              <div className="ent-project-doc-row" key={documentKey}>
                <div className="ent-project-doc-copy">
                  <strong>{clean(item.name) || "서류명 미확인"}</strong>
                  <span>{DocumentReasonLabel(item.reason) || clean(item.origin) || "분류 결과에서 추천된 서류"}</span>
                  {clean(item.file) ? <small>첨부 파일 · {clean(item.file)}</small> : null}
                  {clean(item.requested) ? <small>요청 기록 · {clean(item.requested)}</small> : null}
                </div>
                <div className="ent-project-doc-meta">
                  <em className={`ent-chip ${tone}`}>{status}</em>
                  {clean(item.cat) === "customs" ? (
                    <span className="ent-method-toggle" role="group" aria-label={`${clean(item.name)} 제출 방식`}>
                      <button
                        type="button"
                        className={clean(item.chosen) !== "agency" ? "on" : ""}
                        disabled={busy}
                        onClick={() => saveDocumentChange(documentKey, { chosen: "direct" })}
                      >직접 제출</button>
                      <button
                        type="button"
                        className={clean(item.chosen) === "agency" ? "on agency" : ""}
                        disabled={busy}
                        onClick={() => saveDocumentChange(documentKey, { chosen: "agency" })}
                      >대행 위임</button>
                    </span>
                  ) : null}
                </div>
                <div className="ent-project-doc-actions">
                  {clean(item.quality) === "unverified" ? (
                    <button type="button" className="ent-mini-btn solid" disabled={busy} onClick={() => saveDocumentChange(documentKey, { quality: "verified" })}>
                      원본 확인
                    </button>
                  ) : null}
                  <button type="button" className="ent-mini-btn" disabled={busy} onClick={() => chooseFile(documentKey)}>
                    {busy ? "처리 중…" : clean(item.file) ? "파일 교체" : "파일 업로드"}
                  </button>
                  {clean(item.quality) === "missing" ? (
                    <button
                      type="button"
                      className="ent-mini-btn"
                      disabled={busy}
                      onClick={() => {
                        setRequestDocument(requestDocument === documentKey ? "" : documentKey);
                        setRequestContact("");
                      }}
                    >요청 기록</button>
                  ) : null}
                </div>
                {requestDocument === documentKey ? (
                  <div className="ent-project-request-form">
                    <label htmlFor={`request-${documentKey}`}>요청 대상 연락처</label>
                    <input
                      id={`request-${documentKey}`}
                      className="ent-mgmt-url-input"
                      placeholder="이메일 또는 휴대폰 번호"
                      value={requestContact}
                      autoFocus
                      onChange={(event) => setRequestContact(event.target.value)}
                      onKeyDown={(event) => event.key === "Enter" && recordDocumentRequest(documentKey)}
                    />
                    <button type="button" className="ent-mini-btn solid" disabled={!clean(requestContact) || busy} onClick={() => recordDocumentRequest(documentKey)}>
                      기록 저장
                    </button>
                    <span>현재는 실제 메시지 발송 없이 요청 이력만 저장합니다.</span>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="ent-hint">이 프로젝트에 등록된 서류 항목이 없습니다.</p>
      )}
      {actionError ? <p className="ent-hint ent-action-error" role="alert">서류 처리 오류: {actionError}</p> : null}

      <div className="ent-project-links" aria-label="프로젝트 상세 이동">
        {jobId ? (
          <Link className="ent-project-link" to={`/classification?job=${encodeURIComponent(jobId)}`}>
            분류 과정·근거 확인 <span aria-hidden="true">→</span>
          </Link>
        ) : null}
        {jobId && taric10 ? (
          <Link className="ent-project-link primary" to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(taric10)}?caseId=${encodeURIComponent(caseId)}`}>
            전체 서류 요건 확인 <span aria-hidden="true">→</span>
          </Link>
        ) : null}
      </div>
    </section>
  );
}

export default function EnterprisePage() {
  const [searchParams] = useSearchParams();
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchCases()
      .then((response) => {
        if (!cancelled) {
          setCases(asList(response?.cases));
        }
      })
      .catch((loadError) => {
        if (!cancelled) {
          setError(String(loadError?.message || loadError));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedCaseId = clean(searchParams.get("caseId"));
  const selectedCase = cases.find((item) => clean(item.caseId) === selectedCaseId);
  const updateSelectedDocument = (documentKey, changes) => {
    setCases((current) => current.map((item) => {
      if (clean(item.caseId) !== selectedCaseId) {
        return item;
      }
      return {
        ...item,
        documents: asList(item.documents).map((document) => (
          clean(asObject(document).key) === documentKey
            ? { ...asObject(document), ...changes }
            : document
        )),
      };
    }));
  };

  return (
    <div className="ent theme-light">
      <header className="ent-hero">
        <div>
          <span
            className="ent-logo"
            role="img"
            aria-label="ASAP"
            style={{ WebkitMaskImage: `url(${logo})`, maskImage: `url(${logo})` }}
          />
          <div className="ent-sub">API에 저장된 수출 케이스만 표시합니다.</div>
        </div>
        <div className="ent-case-chip">
          <span>등록 케이스</span>
          <strong>{cases.length}</strong>
          <em>{selectedCaseId || "선택 없음"}</em>
        </div>
      </header>

      {selectedCase ? <SelectedCasePanel caseData={selectedCase} onDocumentChange={updateSelectedDocument} /> : null}
      {!loading && selectedCaseId && !selectedCase ? (
        <section className="ent-card">
          <p className="ent-hint" role="alert">선택한 프로젝트를 찾을 수 없습니다.</p>
        </section>
      ) : null}

      {error ? <section className="ent-card"><p className="ent-hint" role="alert">API 오류: {error}</p></section> : null}

      <section className="ent-card ent-project-management">
        <div className="ent-management-heading">
          <div>
            <div className="ent-card-title">프로젝트 관리</div>
            <p>분류 결과와 서류 준비 상태를 확인하고 필요한 관리 항목으로 이동합니다.</p>
          </div>
          <span className="ent-badge live">실데이터 {cases.length}건</span>
        </div>
        <div className="ent-mgmt-scroll">
          <table className="ent-mgmt">
            <thead>
              <tr>
                <th>프로젝트</th><th>상품</th><th>TARIC10</th><th>서류 현황</th><th>최근 분류</th><th>관리</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((item) => {
                const caseId = clean(item.caseId);
                const taric10 = clean(item.taric10);
                const jobId = clean(item.lastJobId);
                const documents = asList(item.documents);
                const activeDocumentCount = documents.filter(DocumentIsActive).length;
                const completion = documents.length ? Math.round((activeDocumentCount / documents.length) * 100) : 0;
                return (
                  <tr className={`ent-mgmt-row ${selectedCaseId === caseId ? "open" : ""}`} key={caseId}>
                    <td className="ent-mgmt-id">{caseId}</td>
                    <td className="ent-mgmt-name">
                      <strong>{clean(item.name) || "상품명 미입력"}</strong>
                      <span>{clean(item.destination) || "목적지 미입력"}</span>
                    </td>
                    <td className="ent-mgmt-hs"><b>{taric10 || "-"}</b></td>
                    <td>
                      <div className="ent-mgmt-docs">
                        <b>{activeDocumentCount} / {documents.length}</b>
                        <span className="ent-mgmt-bar" aria-label={`서류 진행률 ${completion}%`}>
                          <span style={{ width: `${completion}%` }} />
                        </span>
                      </div>
                    </td>
                    <td className="ent-mgmt-id">{jobId || "-"}</td>
                    <td>
                      <Link
                        className={`ent-management-link ${selectedCaseId === caseId ? "active" : ""}`}
                        aria-current={selectedCaseId === caseId ? "page" : undefined}
                        to={`/enterprise?caseId=${encodeURIComponent(caseId)}&panel=docs`}
                      >
                        {selectedCaseId === caseId ? "서류 관리 열림" : "서류 관리 열기"}
                      </Link>
                    </td>
                  </tr>
                );
              })}
              {!loading && !cases.length ? (
                <tr><td colSpan={6}>API에 저장된 프로젝트가 없습니다.</td></tr>
              ) : null}
              {loading ? <tr><td colSpan={6}>불러오는 중…</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
