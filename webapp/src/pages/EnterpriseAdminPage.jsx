import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCases } from "../lib/enterpriseApi.js";

// ASAP 내부용 — 계약 기업들의 서류 제출 진행 현황 관제.
// 기업 서류는 고객에게 제출 URL만 발급되고, 실제 수취·검토는 이 페이지에서 이뤄진다.
// (데모 데이터 — 실제로는 케이스/서류 테이블 연동 예정)
const COMPANIES = [
  {
    id: "EXP-2026-0715-003",
    name: "연안식당",
    product: "재첩국 밀키트 500g (냉동)",
    dest: "독일 (함부르크항)",
    plan: "스탠다드",
    status: ["검토 대기", "warn"],
    docs: {
      product: [
        ["성분명세서 COI", "미검증 사본"],
        ["HACCP · 시설 등록증", "미검증 사본"],
        ["라벨 원안", "누락"],
        ["제품 사양서", "누락"],
      ],
      customs: [
        ["상업송장 (CI)", "원본 확인"],
        ["포장명세서 (PL)", "원본 확인"],
        ["원산지 신고 문안", "대행 진행"],
        ["선적 서류 (B/L)", "대행 진행"],
      ],
      company: [
        ["사업자등록증", "URL 발급 · 수취 대기"],
        ["수출자 신고 정보", "미발급"],
      ],
    },
  },
  {
    id: "EXP-2026-0711-014",
    name: "섬진강식품",
    product: "김치찌개 밀키트 800g",
    dest: "네덜란드 (로테르담항)",
    plan: "프리미엄",
    status: ["보완 요청", "miss"],
    docs: {
      product: [
        ["성분명세서 COI", "원본 확인"],
        ["HACCP · 시설 등록증", "원본 확인"],
        ["라벨 원안", "반려 — 알레르겐 표기 누락"],
      ],
      customs: [
        ["상업송장 (CI)", "대행 진행"],
        ["포장명세서 (PL)", "대행 진행"],
        ["원산지 신고 문안", "대행 진행"],
      ],
      company: [
        ["사업자등록증", "수취 완료"],
        ["수출자 신고 정보", "수취 완료"],
      ],
    },
  },
  {
    id: "EXP-2026-0708-027",
    name: "고래사어묵",
    product: "어묵탕 세트 1.2kg (냉동)",
    dest: "프랑스 (르아브르항)",
    plan: "스탠다드",
    status: ["통관 진행", "ok"],
    docs: {
      product: [
        ["성분명세서 COI", "원본 확인"],
        ["HACCP · 시설 등록증", "원본 확인"],
        ["라벨 원안", "원본 확인"],
      ],
      customs: [
        ["상업송장 (CI)", "원본 확인"],
        ["포장명세서 (PL)", "원본 확인"],
        ["원산지 신고 문안", "원본 확인"],
        ["위생증명서 FISH-CRUST-HC", "발급 완료"],
      ],
      company: [
        ["사업자등록증", "수취 완료"],
        ["수출자 신고 정보", "수취 완료"],
      ],
    },
  },
  {
    id: "EXP-2026-0702-041",
    name: "담양죽순영농조합",
    product: "죽순 장아찌 350g",
    dest: "이탈리아 (제노바항)",
    plan: "라이트",
    status: ["서류 수집", "info"],
    docs: {
      product: [
        ["성분명세서 COI", "누락"],
        ["라벨 원안", "누락"],
      ],
      customs: [
        ["상업송장 (CI)", "누락"],
        ["포장명세서 (PL)", "누락"],
      ],
      company: [
        ["사업자등록증", "URL 발급 · 수취 대기"],
        ["수출자 신고 정보", "URL 발급 · 수취 대기"],
      ],
    },
  },
];

const CAT_LABELS = { product: "물품", customs: "통관", company: "기업" };

const DONE_STATES = ["원본 확인", "수취 완료", "발급 완료"];

function docStats(list) {
  const done = list.filter(([, s]) => DONE_STATES.includes(s)).length;
  return [done, list.length];
}

function statusTone(state) {
  if (DONE_STATES.includes(state)) return "ok";
  if (state.includes("반려")) return "miss";
  if (state === "누락" || state === "미발급") return "miss";
  if (state === "대행 진행") return "violet";
  return "warn";
}

function ProgressCell({ list }) {
  const [done, total] = docStats(list);
  return (
    <div className="eadm-progress">
      <span className="eadm-progress-num">{done}/{total}</span>
      <span className="eadm-progress-bar">
        <span style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
      </span>
    </div>
  );
}

export default function EnterpriseAdminPage() {
  const [openId, setOpenId] = useState(COMPANIES[0].id);
  const open = COMPANIES.find((c) => c.id === openId);

  // 수집 원장(/api/enterprise/cases)에서 실데이터 케이스 로드 — 백엔드 미기동이면 빈 목록
  const [liveCases, setLiveCases] = useState([]);
  useEffect(() => {
    fetchCases().then((response) => {
      if (Array.isArray(response?.cases)) {
        setLiveCases(response.cases);
      }
    });
  }, []);

  return (
    <div className="classification-admin-shell">
      <header className="cadm-hero">
        <div className="cadm-eyebrow">ASAP INTERNAL</div>
        <h1 className="cadm-title">기업 서류 관제</h1>
        <p className="cadm-subtitle">
          계약 기업별 서류 제출 진행 현황 — 기업 서류는 발급된 URL로 수취하며, 검토 확정도 여기서 합니다.
          파이프라인 런 열람은 <Link to="/admin">Run Inspector</Link>.
        </p>
      </header>

      <section className="cadm-section">
        {liveCases.length ? (
          <div className="cadm-panel cadm-panel-wide">
            <div className="cadm-panel-title">수집 원장 — 실데이터 케이스 ({liveCases.length})</div>
            <div className="cadm-table-scroll">
              <table className="cadm-table eadm-table">
                <thead>
                  <tr>
                    <th>케이스</th><th>상품</th><th>판매 채널 · URL</th><th>판매가</th><th>월 물량</th>
                    <th>서류 이벤트</th><th>최근 분류 job</th>
                  </tr>
                </thead>
                <tbody>
                  {liveCases.map((c) => (
                    <tr key={c.caseId}>
                      <td className="eadm-mono">{c.caseId}</td>
                      <td><b>{c.name || "-"}</b></td>
                      <td className="eadm-mono">{c.channel ? `${c.channel} · ` : ""}{c.url || "-"}</td>
                      <td>{c.price ? `${Number(c.price).toLocaleString()}원` : "-"}</td>
                      <td>{c.volume ? Number(c.volume).toLocaleString() : "-"}</td>
                      <td>{Object.keys(c.docs || {}).length}종 · {c.events || 0}건</td>
                      <td className="eadm-mono">{c.lastJobId || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="cadm-muted" style={{ marginTop: 8 }}>
              /api/enterprise 이벤트 원장에서 집계 — 판매 채널·가격·물량·서류 흐름·분류 귀속이 케이스 단위로 쌓입니다.
            </p>
          </div>
        ) : null}
        <div className="cadm-panel cadm-panel-wide">
          <div className="cadm-panel-title">계약 기업 ({COMPANIES.length})</div>
          <div className="cadm-table-scroll">
            <table className="cadm-table eadm-table">
              <thead>
                <tr>
                  <th>기업</th>
                  <th>케이스</th>
                  <th>상품 → 목적지</th>
                  <th>플랜</th>
                  <th>물품 서류</th>
                  <th>통관 서류</th>
                  <th>기업 서류</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                {COMPANIES.map((c) => (
                  <tr
                    key={c.id}
                    className={`eadm-row ${openId === c.id ? "open" : ""}`}
                    onClick={() => setOpenId(c.id)}
                  >
                    <td><b>{c.name}</b></td>
                    <td className="eadm-mono">{c.id}</td>
                    <td>{c.product} → {c.dest}</td>
                    <td>{c.plan}</td>
                    <td><ProgressCell list={c.docs.product} /></td>
                    <td><ProgressCell list={c.docs.customs} /></td>
                    <td><ProgressCell list={c.docs.company} /></td>
                    <td><span className={`eadm-chip ${c.status[1]}`}>{c.status[0]}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {open ? (
          <div className="cadm-panel cadm-panel-wide">
            <div className="cadm-panel-title">
              {open.name} · {open.id} — 서류 상세
            </div>
            <div className="eadm-detail">
              {Object.entries(open.docs).map(([cat, list]) => (
                <div className="eadm-detail-col" key={cat}>
                  <div className="eadm-detail-head">{CAT_LABELS[cat]} 서류</div>
                  {list.map(([name, state]) => (
                    <div className="eadm-detail-row" key={name}>
                      <span>{name}</span>
                      <span className={`eadm-chip ${statusTone(state)}`}>{state}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <p className="cadm-muted" style={{ marginTop: 12 }}>
              수취한 기업 서류의 검토 확정, 보완 요청 발송은 이 화면에서 처리합니다 (데모 — 실제 액션은 케이스 테이블 연동 후).
            </p>
          </div>
        ) : null}
      </section>
    </div>
  );
}
