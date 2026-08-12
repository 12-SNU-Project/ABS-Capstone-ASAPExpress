import { asObject, formatValue, labelFor } from "../lib/format.js";

export default function KeyValueRows({ data, keys, limit = 12 }) {
  const source = asObject(data);
  const rawEntries = Array.isArray(keys)
    ? keys.map((key) => [key, source[key]])
    : Object.entries(source).filter(([key]) => !!labelFor(key));
  const entries = rawEntries
    .filter(([key, value]) => labelFor(key) && value !== undefined && value !== null && formatValue(value) !== "")
    .slice(0, limit);

  if (!entries.length) {
    return <div className="cjs-muted">현재 응답에 표시할 핵심 정보가 없습니다.</div>;
  }
  return entries.map(([key, value]) => (
    <div className="cjs-kv" key={key}>
      <span>{labelFor(key)}</span>
      <strong>{formatValue(value)}</strong>
    </div>
  ));
}
