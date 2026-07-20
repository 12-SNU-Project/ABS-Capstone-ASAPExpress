import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCases } from "../lib/enterpriseApi.js";
import { asList, clean } from "../lib/format.js";

export default function EnterpriseAdminPage() {
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

  return (
    <div className="classification-admin-shell">
      <header className="cadm-hero">
        <div className="cadm-eyebrow">ASAP INTERNAL</div>
        <h1 className="cadm-title">기업 서류 관제</h1>
        <p className="cadm-subtitle">
          `/api/enterprise/cases`에 저장된 케이스만 표시합니다. 파이프라인 런은 <Link to="/admin">Run Inspector</Link>에서 확인합니다.
        </p>
      </header>

      <section className="cadm-section">
        <div className="cadm-panel cadm-panel-wide">
          <div className="cadm-panel-title">수집 케이스 ({cases.length})</div>
          {error ? <div className="cadm-muted">API 오류: {error}</div> : null}
          {loading ? <div className="cadm-muted">불러오는 중…</div> : null}
          {!loading && !error && !cases.length ? (
            <div className="cadm-muted">저장된 케이스가 없습니다.</div>
          ) : null}
          {cases.length ? (
            <div className="cadm-table-scroll">
              <table className="cadm-table eadm-table">
                <thead>
                  <tr>
                    <th>케이스</th><th>상품</th><th>목적지</th><th>상품 URL</th><th>TARIC10</th>
                    <th>서류</th><th>이벤트</th><th>최근 분류</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((item) => (
                    <tr key={item.caseId}>
                      <td className="eadm-mono">{clean(item.caseId)}</td>
                      <td><b>{clean(item.name) || "-"}</b></td>
                      <td>{clean(item.destination) || "-"}</td>
                      <td className="eadm-mono">{clean(item.url) || "-"}</td>
                      <td className="eadm-mono">{clean(item.taric10) || "-"}</td>
                      <td>{asList(item.documents).length}종</td>
                      <td>{Number(item.events) || 0}건</td>
                      <td className="eadm-mono">{clean(item.lastJobId) || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
