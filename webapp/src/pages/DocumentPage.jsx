import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import DocumentPackageDetail from "../components/DocumentPackageDetail";
import { importClassification } from "../lib/enterpriseApi.js";
import { getJson } from "../lib/api.js";
import { asList, clean } from "../lib/format.js";

export default function DocumentPage() {
  const { jobId, taric10 } = useParams();
  const navigate = useNavigate();
  const [packages, setPackages] = useState([]);
  const [packageData, setPackageData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const saveToEnterprise = async () => {
    const selectedTaric10 = clean(packageData?.taric10) || taric10;
    if (!selectedTaric10 || !window.confirm("선택한 TARIC10과 필요 서류 목록을 수출 상품 관리에 등록하시겠습니까?")) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const response = await importClassification({ jobId, taric10: selectedTaric10 });
      if (!response?.caseId) {
        throw new Error("수출 상품을 등록하지 못했습니다.");
      }
      navigate(`/enterprise?caseId=${encodeURIComponent(response.caseId)}&panel=docs`);
    } catch (saveError) {
      setError(String(saveError?.message || saveError));
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      setPackageData(null);
      try {
        const detail = await getJson(
          `/api/runs/${encodeURIComponent(jobId)}/document-packages/${encodeURIComponent(taric10)}`,
        );
        if (!cancelled) {
          setPackageData(detail.document_package || detail);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(String(loadError?.message || loadError));
        }
      }
      try {
        const collection = await getJson(
          `/api/runs/${encodeURIComponent(jobId)}/document-packages`,
        );
        if (!cancelled) {
          setPackages(asList(collection.packages));
        }
      } catch {
        /* 목록은 보조 정보 — 실패해도 상세 렌더는 유지 */
      }
      if (!cancelled) {
        setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [jobId, taric10]);

  return (
    <div className="docpage">
      <header className="docpage-header">
        <div>
          <div className="docpage-eyebrow">
            <Link to="/classification">← 분류 워크벤치</Link>
          </div>
          <h1 className="docpage-title">TARIC 상세 서류 추천</h1>
          <div className="docpage-subtitle">
            run {jobId} · backend document package DTO를 React 컴포넌트로 직접 렌더링합니다.
          </div>
        </div>
        <div className="docpage-actions">
          <div className="docpage-pill">TARIC10 {clean(packageData?.taric10) || taric10}</div>
          <button type="button" className="docpage-save" disabled={!packageData || saving} onClick={saveToEnterprise}>
            {saving ? "등록 중..." : "수출 상품 관리에 등록"}
          </button>
        </div>
      </header>

      {packages.length > 1 ? (
        <nav className="docpage-tabs" aria-label="이 run의 document packages">
          {packages.map((pkg) => {
            const target = clean(pkg.taric10 || pkg.document_package_id);
            const active = target === taric10 || clean(pkg.taric10) === clean(packageData?.taric10);
            return (
              <Link
                key={clean(pkg.document_package_id) || target}
                to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(target)}`}
                className={`docpage-tab ${active ? "active" : ""}`}
              >
                {clean(pkg.taric10) || clean(pkg.document_package_id)}
              </Link>
            );
          })}
        </nav>
      ) : null}

      {error ? <div className="docpage-error">{error}</div> : null}
      {loading && !packageData ? (
        <div className="docpage-loading">서류 추천 데이터를 불러오는 중입니다.</div>
      ) : null}
      {!loading && !error && !packageData ? (
        <div className="docpage-loading">표시할 document package가 없습니다.</div>
      ) : null}
      {packageData ? <DocumentPackageDetail packageData={packageData} /> : null}
    </div>
  );
}
