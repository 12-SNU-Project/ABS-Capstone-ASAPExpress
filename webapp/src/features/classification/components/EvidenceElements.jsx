import { asList, clean } from "@/lib/format.js";

const FACT_LABELS = {
  primary_ingredient_ratio: "주원료 함유율",
  animal_origin_content_pct: "동물성 원료 함유율",
  composition_pct: "성분별 함유율",
  ingredient_percentages: "성분별 함유율",
  principal_ingredient: "주원료",
  origin_country: "상품 원산국",
  intended_use: "상품 용도",
};

export function FactLabel(value) {
  const key = clean(value);
  return FACT_LABELS[key] || key.replaceAll("_", " ");
}

export function EvidenceTerms({ label, terms }) {
  const list = asList(terms).map((term) => clean(term)).filter(Boolean);
  if (!list.length) return null;
  return (
    <div className="cjs-term-group">
      <div className="cjs-subpanel-title">{label} ({list.length})</div>
      <div className="cjs-chip-row">
        {list.slice(0, 16).map((term, index) => (
          <span className="cjs-chip" key={index}>{term}</span>
        ))}
      </div>
    </div>
  );
}

export function PrecedentSummary({ cases }) {
  const list = asList(cases);
  if (!list.length) {
    return <div className="cjs-muted">이 후보와 연결된 유사 판례가 없습니다.</div>;
  }
  return (
    <div className="cjs-precedent-list">
      {list.map((item, index) => (
        <div className="cjs-precedent" key={index}>
          <div className="cjs-precedent-ref">{clean(item.evidence_ref)}</div>
          <div className="cjs-precedent-sim">{clean(item.similarity_comment)}</div>
          {clean(item.difference_comment) ? (
            <div className="cjs-precedent-diff">{clean(item.difference_comment)}</div>
          ) : null}
          {clean(item.case_summary) ? (
            <details className="cjs-precedent-more">
              <summary>판결문 요약</summary>
              <div className="cjs-precedent-body">{clean(item.case_summary)}</div>
            </details>
          ) : null}
        </div>
      ))}
    </div>
  );
}
