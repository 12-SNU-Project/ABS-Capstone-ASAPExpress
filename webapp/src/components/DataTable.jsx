import { asList, asObject, previewValue } from "../lib/format.js";

/**
 * 컴팩트 데이터 표. columns: [{ key, label, variant?: "mono" | "pill" }]
 * variant "pill"은 값에 따라 ok(accepted/true)·warn 톤 배지로 렌더한다.
 */
export default function DataTable({ rows, columns, limit = 40, emptyMessage = "데이터가 없습니다." }) {
  const list = asList(rows).slice(0, limit);
  if (!list.length) {
    return <div className="cjs-muted">{emptyMessage}</div>;
  }
  const resolvedColumns =
    columns ||
    [...new Set(list.flatMap((row) => Object.keys(asObject(row))))].map((key) => ({
      key,
      label: key,
    }));
  return (
    <div className="cjs-table-scroll">
      <table className="cjs-table">
        <thead>
          <tr>
            {resolvedColumns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {list.map((row, index) => (
            <tr key={index}>
              {resolvedColumns.map((column) => {
                const value = asObject(row)[column.key];
                const text = previewValue(value, 220);
                if (column.variant === "pill" && text) {
                  const ok = ["accepted", "예", "true", "ok", "none"].includes(
                    String(value).toLowerCase() === "true" ? "true" : text.toLowerCase(),
                  );
                  return (
                    <td key={column.key}>
                      <span className={`cjs-cell-pill ${ok ? "ok" : "warn"}`}>{text}</span>
                    </td>
                  );
                }
                return (
                  <td key={column.key} className={column.variant === "mono" ? "cjs-cell-mono" : ""}>
                    {text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
