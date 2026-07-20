import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import logo from "../assets/asap_black.png";
import { fetchCases, registerProduct } from "../lib/enterpriseApi.js";
import { asList, clean } from "../lib/format.js";

const EMPTY_FORM = {
  name: "",
  url: "",
  destination: "",
  price: "",
  volume: "",
  channel: "",
};

function displayNumber(value, suffix = "") {
  const number = Number(value);
  return number ? `${number.toLocaleString()}${suffix}` : "-";
}

export default function EnterprisePage() {
  const [searchParams] = useSearchParams();
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

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

  const setField = (key) => (event) => {
    setForm((current) => ({ ...current, [key]: event.target.value }));
  };

  const addProduct = async () => {
    const name = clean(form.name);
    if (!name || saving) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const response = await registerProduct({
        name,
        url: clean(form.url),
        destination: clean(form.destination),
        price: Number(form.price) || 0,
        volume: Number(form.volume) || 0,
        channel: clean(form.channel),
      });
      if (!response?.case?.caseId) {
        throw new Error("등록된 케이스 응답이 없습니다.");
      }
      setCases((current) => [
        response.case,
        ...current.filter((item) => item.caseId !== response.case.caseId),
      ]);
      setForm(EMPTY_FORM);
    } catch (saveError) {
      setError(String(saveError?.message || saveError));
    } finally {
      setSaving(false);
    }
  };

  const selectedCaseId = clean(searchParams.get("caseId"));

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

      <section className="ent-card">
        <div className="ent-card-title">수출 상품 등록</div>
        <div className="ent-add-form">
          <input aria-label="제품명" className="ent-mgmt-url-input grow" placeholder="제품명" value={form.name} onChange={setField("name")} />
          <input aria-label="상품 URL" className="ent-mgmt-url-input grow" placeholder="상품 URL" value={form.url} onChange={setField("url")} />
          <input aria-label="목적지" className="ent-mgmt-url-input" placeholder="목적지" value={form.destination} onChange={setField("destination")} />
          <input aria-label="판매가" className="ent-mgmt-url-input" inputMode="numeric" placeholder="판매가" value={form.price} onChange={setField("price")} />
          <input aria-label="월 물량" className="ent-mgmt-url-input" inputMode="numeric" placeholder="월 물량" value={form.volume} onChange={setField("volume")} />
          <input aria-label="판매 채널" className="ent-mgmt-url-input" placeholder="판매 채널" value={form.channel} onChange={setField("channel")} />
          <button type="button" className="ent-mini-btn solid" disabled={!clean(form.name) || saving} onClick={addProduct}>
            {saving ? "등록 중…" : "등록"}
          </button>
        </div>
        {error ? <p className="ent-hint" role="alert">API 오류: {error}</p> : null}
      </section>

      <section className="ent-card">
        <div className="ent-card-title">
          수출 상품 관리
          <span className="ent-badge live">실데이터 {cases.length}건</span>
        </div>
        <div className="ent-mgmt-scroll">
          <table className="ent-mgmt">
            <thead>
              <tr>
                <th>관리 ID</th><th>제품명</th><th>상품 URL</th><th>목적지</th><th>TARIC10</th>
                <th>서류</th><th>판매가</th><th>월 물량</th><th>최근 분류</th><th>관리</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((item) => {
                const caseId = clean(item.caseId);
                const taric10 = clean(item.taric10);
                const jobId = clean(item.lastJobId);
                const documentCount = asList(item.documents).length;
                return (
                  <tr className={`ent-mgmt-row ${selectedCaseId === caseId ? "open" : ""}`} key={caseId}>
                    <td className="ent-mgmt-id">{caseId}</td>
                    <td className="ent-mgmt-name">{clean(item.name) || "-"}</td>
                    <td className="ent-mgmt-url"><span className="ent-mgmt-url-text">{clean(item.url) || "-"}</span></td>
                    <td>{clean(item.destination) || "-"}</td>
                    <td className="ent-mgmt-hs"><b>{taric10 || "-"}</b></td>
                    <td>{documentCount}종</td>
                    <td>{displayNumber(item.price, "원")}</td>
                    <td>{displayNumber(item.volume)}</td>
                    <td className="ent-mgmt-id">{jobId || "-"}</td>
                    <td>
                      {jobId ? <Link className="ent-link" to={`/admin?job=${encodeURIComponent(jobId)}`}>런 보기</Link> : null}
                      {jobId && taric10 ? <Link className="ent-link" to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(taric10)}`}>서류 보기</Link> : null}
                    </td>
                  </tr>
                );
              })}
              {!loading && !cases.length ? (
                <tr><td colSpan={10}>API에 저장된 수출 케이스가 없습니다.</td></tr>
              ) : null}
              {loading ? <tr><td colSpan={10}>불러오는 중…</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
