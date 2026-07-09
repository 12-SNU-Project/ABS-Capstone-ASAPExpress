import { asList, asObject, clean, previewValue } from "../lib/format.js";

function joinList(value) {
  return asList(value)
    .map((item) => clean(item))
    .filter(Boolean)
    .join(", ");
}

function yesNo(value) {
  return value ? "예" : "아니오";
}

function deriveDocumentRows(packageData) {
  const requiredDocuments = asList(packageData.required_documents);
  if (requiredDocuments.length) {
    return requiredDocuments;
  }
  const documents = asObject(asObject(packageData.checklist_summary).documents);
  const rows = [];
  Object.entries(documents).forEach(([status, values]) => {
    asList(values).forEach((value) => {
      const title = clean(value);
      if (!title) {
        return;
      }
      rows.push({
        title,
        code: title.toUpperCase().replace(/[^A-Z0-9]+/g, "_"),
        doc_kind: status,
        required_when: status,
        celex_id: "",
      });
    });
  });
  return rows;
}

function Section({ title, description = "", children }) {
  return (
    <section className="ddv-section">
      <div className="ddv-section-head">
        <h2 className="ddv-section-title">{title}</h2>
        {description ? <p className="ddv-section-desc">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

function EmptyBlock({ message }) {
  return <div className="ddv-empty">{message}</div>;
}

function MetricGrid({ items }) {
  return (
    <div className="ddv-metric-grid">
      {items.map((item) => (
        <div className="ddv-metric-card" key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
}

function PillRow({ items, emptyMessage = "표시할 항목이 없습니다." }) {
  const rows = asList(items).map((item) => clean(item)).filter(Boolean);
  if (!rows.length) {
    return <EmptyBlock message={emptyMessage} />;
  }
  return (
    <div className="ddv-pill-row">
      {rows.map((item) => (
        <span className="ddv-pill" key={item}>{item}</span>
      ))}
    </div>
  );
}

function DataTable({ columns, rows, emptyMessage }) {
  const normalizedRows = asList(rows);
  if (!normalizedRows.length) {
    return <EmptyBlock message={emptyMessage} />;
  }
  return (
    <div className="ddv-table-wrap">
      <table className="ddv-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {normalizedRows.map((row, index) => {
            const source = asObject(row);
            return (
              <tr key={`${index}_${previewValue(source[columns[0].key], 40)}`}>
                {columns.map((column) => (
                  <td key={column.key}>
                    {column.render
                      ? column.render(source)
                      : previewValue(source[column.key], column.limit || 200)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RegulationCards({ rows }) {
  const records = asList(rows);
  if (!records.length) {
    return <EmptyBlock message="제품 규제 규칙이 없습니다." />;
  }
  return (
    <div className="ddv-card-grid">
      {records.map((row, index) => {
        const source = asObject(row);
        return (
          <article className="ddv-card" key={`${clean(source.domain)}_${index}`}>
            <div className="ddv-card-head">
              <strong>{clean(source.domain) || "unknown"}</strong>
              <span>{clean(source.applies) || "possibly_applies"}</span>
            </div>
            <p>{clean(source.scope) || "scope 없음"}</p>
            <div className="ddv-card-meta">{clean(source.rule_family) || "rule family 없음"}</div>
            {asList(source.missing_facts).length ? (
              <div className="ddv-card-foot">부족 정보: {joinList(source.missing_facts)}</div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

function LinkCards({ links }) {
  const rows = asList(links);
  if (!rows.length) {
    return <EmptyBlock message="추가 외부 조회 링크가 없습니다." />;
  }
  return (
    <div className="ddv-link-grid">
      {rows.map((row, index) => {
        const source = asObject(row);
        const url = clean(source.url);
        return (
          <a
            key={`${clean(source.name)}_${index}`}
            className="ddv-link-card"
            href={url || undefined}
            target="_blank"
            rel="noreferrer"
          >
            <strong>{clean(source.name) || "외부 링크"}</strong>
            <span>{url || "URL 없음"}</span>
          </a>
        );
      })}
    </div>
  );
}

function SignalList({ items, emptyMessage }) {
  const rows = asList(items);
  if (!rows.length) {
    return <EmptyBlock message={emptyMessage} />;
  }
  return (
    <div className="ddv-signal-list">
      {rows.map((row, index) => {
        const source = asObject(row);
        return (
          <article className="ddv-signal" key={`${clean(source.type)}_${index}`}>
            <div className="ddv-signal-head">
              <strong>{clean(source.type) || "signal"}</strong>
              {clean(source.candidate_id) ? <span>{clean(source.candidate_id)}</span> : null}
            </div>
            <p>{clean(source.reason) || "설명 없음"}</p>
            {asList(source.missing_facts).length ? (
              <div className="ddv-signal-foot">부족 정보: {joinList(source.missing_facts)}</div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

export default function DocumentPackageDetail({ packageData }) {
  const pkg = asObject(packageData);
  if (!Object.keys(pkg).length) {
    return <EmptyBlock message="문서 패키지 데이터가 없습니다." />;
  }

  const summary = asObject(pkg.summary);
  const basicDuty = asObject(pkg.basic_duty);
  const requiredDocuments = deriveDocumentRows(pkg);
  const customsChecks = asList(pkg.customs_check_items);
  const preferentialEvidence = asList(pkg.preferential_evidence);
  const productRegulations = asList(pkg.product_regulations);
  const celexBasis = asList(pkg.celex_basis);
  const externalLookup = asList(pkg.external_lookup);
  const missingFacts = asList(pkg.missing_facts);
  const backtrackingSignals = asList(pkg.backtracking_signals);
  const conflicts = asList(pkg.conflicts);
  const requirements = asList(pkg.requirements);

  const metrics = [
    { label: "TARIC10", value: clean(pkg.taric10) || "-" },
    { label: "CN8", value: clean(pkg.cn8) || "-" },
    { label: "기본 관세", value: clean(basicDuty.rate || summary.duty) || "-" },
    { label: "필수 문서", value: `${requiredDocuments.length}건` },
    { label: "세관/통제", value: `${customsChecks.length}건` },
    { label: "제품 규제", value: `${productRegulations.length}건` },
  ];

  const overviewRows = [
    ["문서 패키지 ID", clean(pkg.document_package_id) || "-"],
    ["브랜치 분기", pkg.taric10_branch_count ? `${pkg.taric10_branch_index}/${pkg.taric10_branch_count}` : "단일 branch"],
    ["분기 해석 방식", clean(pkg.taric10_resolution_mode) || "-"],
    ["데이터 존재", yesNo(!!pkg.has_data)],
    ["기본 관세 근거", clean(basicDuty.measure_type) || "-"],
    ["기본 관세 CELEX", clean(basicDuty.celex_id) || "-"],
  ];

  return (
    <div className="ddv-shell">
      <Section
        title="개요"
        description="공개 API document package DTO를 직접 렌더링합니다. 내부 raw artifact에는 의존하지 않습니다."
      >
        <MetricGrid items={metrics} />
        <div className="ddv-overview-grid">
          {overviewRows.map(([label, value]) => (
            <div className="ddv-overview-row" key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        <div className="ddv-subblock">
          <h3>요약된 주요 요구사항</h3>
          <PillRow items={summary.main_requirements} emptyMessage="요약된 주요 요구사항이 없습니다." />
        </div>
        <div className="ddv-subblock">
          <h3>도메인 / 확인 필요 정보</h3>
          <PillRow items={summary.domains} emptyMessage="추정 도메인이 없습니다." />
          {asList(summary.unknowns).length ? (
            <div className="ddv-inline-note">확인 필요: {joinList(summary.unknowns)}</div>
          ) : null}
        </div>
      </Section>

      <Section title="필수/조건 문서" description="measure 기반 required document와 checklist 요약 fallback을 함께 반영합니다.">
        <DataTable
          rows={requiredDocuments}
          emptyMessage="표시할 문서가 없습니다."
          columns={[
            { key: "title", label: "문서명" },
            { key: "code", label: "코드" },
            { key: "doc_kind", label: "유형" },
            { key: "required_when", label: "요구 조건" },
            { key: "celex_id", label: "CELEX" },
          ]}
        />
      </Section>

      <Section title="세관/통제 조치" description="검역·통제·제한 조치 bucket입니다.">
        <DataTable
          rows={customsChecks}
          emptyMessage="세관/통제 조치가 없습니다."
          columns={[
            { key: "measure_type", label: "Measure" },
            { key: "applies_to_korea", label: "KR 적용", render: (row) => yesNo(!!row.applies_to_korea) },
            { key: "origins", label: "대상 원산지", render: (row) => joinList(row.origins) || "-" },
            { key: "cert_codes", label: "증빙 코드", render: (row) => joinList(row.cert_codes) || "-" },
            { key: "legal_base", label: "법적 근거" },
            { key: "celex_id", label: "CELEX" },
          ]}
        />
      </Section>

      <Section title="관세 / 특혜" description="기본 관세와 preferential evidence를 분리해서 표시합니다.">
        <div className="ddv-duty-card">
          <strong>{clean(basicDuty.rate || summary.duty) || "-"}</strong>
          <span>{clean(basicDuty.measure_type) || "기본 관세 정보 없음"}</span>
          {clean(basicDuty.legal_base) ? <em>{clean(basicDuty.legal_base)}</em> : null}
        </div>
        <DataTable
          rows={preferentialEvidence}
          emptyMessage="특혜/우대 근거가 없습니다."
          columns={[
            { key: "measure_type", label: "Measure" },
            { key: "origins", label: "대상 원산지", render: (row) => joinList(row.origins) || "-" },
            { key: "duty", label: "관세", render: (row) => previewValue(asObject(row.duty).rate || asObject(row.duty).text, 120) || "-" },
            { key: "legal_base", label: "법적 근거" },
            { key: "celex_id", label: "CELEX" },
          ]}
        />
      </Section>

      <Section title="제품 규제 도메인" description="backend domain router가 추정한 제품 규제 family입니다.">
        <RegulationCards rows={productRegulations} />
      </Section>

      <Section title="법령 근거" description="measure에서 추출된 CELEX basis입니다.">
        <DataTable
          rows={celexBasis}
          emptyMessage="표시할 CELEX 근거가 없습니다."
          columns={[
            { key: "celex_id", label: "CELEX" },
            { key: "title", label: "제목" },
            { key: "for_measure_type", label: "연결 measure" },
            { key: "match_status", label: "매치 상태" },
          ]}
        />
      </Section>

      <Section title="리스크 / 확인 필요" description="classification 재검토나 추가 사실 확인이 필요한 지점을 보여줍니다.">
        <div className="ddv-risk-grid">
          <div>
            <h3>부족 정보</h3>
            <PillRow items={missingFacts} emptyMessage="부족 정보가 없습니다." />
          </div>
          <div>
            <h3>충돌</h3>
            <PillRow items={conflicts} emptyMessage="충돌 항목이 없습니다." />
          </div>
        </div>
        <SignalList items={backtrackingSignals} emptyMessage="분류 backtracking signal이 없습니다." />
      </Section>

      <Section title="외부 확인 링크" description="destination-side 확인이 필요한 공식/준공식 외부 조회 지점입니다.">
        <LinkCards links={externalLookup} />
      </Section>

      <Section title="원본 공개 필드" description="DTO에 남아 있는 추가 field를 그대로 확인할 수 있는 fallback 영역입니다.">
        <details className="ddv-details">
          <summary>requirements ({requirements.length})</summary>
          <pre>{JSON.stringify(requirements, null, 2)}</pre>
        </details>
        <details className="ddv-details">
          <summary>checklist_summary</summary>
          <pre>{JSON.stringify(asObject(pkg.checklist_summary), null, 2)}</pre>
        </details>
        <details className="ddv-details">
          <summary>document_package JSON</summary>
          <pre>{JSON.stringify(pkg, null, 2)}</pre>
        </details>
      </Section>
    </div>
  );
}

