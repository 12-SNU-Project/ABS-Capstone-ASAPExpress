import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { asList, asObject, clean } from "@/lib/format.js";

const INTENDED_USE_OPTIONS = [
  ["human consumption", "최종 소비용"],
  ["further processing", "추가 가공용"],
  ["animal feed", "동물 사료용"],
  ["non-food use", "비식품용"],
];

function CreateIngredient(role = "secondary") {
  return { role, name: "", percentage: "" };
}

function ValidateStructuredInput(form) {
  const errors = { ingredientRows: {} };
  const completedRows = [];

  asList(form.ingredients).forEach((row, index) => {
    const name = clean(row?.name);
    const percentageText = clean(row?.percentage);
    if (!name && !percentageText) return;
    if (!name) {
      errors.ingredientRows[index] = "재료명을 입력하세요.";
      return;
    }
    if (name.length > 100 || !/[A-Za-z가-힣]/.test(name)) {
      errors.ingredientRows[index] = "재료명은 한글 또는 영문을 포함해 100자 이내로 입력하세요.";
      return;
    }
    const percentage = Number(percentageText);
    if (!percentageText || !Number.isFinite(percentage) || percentage <= 0 || percentage > 100) {
      errors.ingredientRows[index] = "함유율은 0 초과 100 이하의 숫자로 입력하세요.";
      return;
    }
    completedRows.push({ ...row, name, percentage });
  });

  const normalizedNames = completedRows.map((row) => row.name.toLocaleLowerCase());
  if (new Set(normalizedNames).size !== normalizedNames.length) {
    errors.ingredients = "같은 재료명을 중복해서 입력할 수 없습니다.";
  } else if (completedRows.reduce((sum, row) => sum + row.percentage, 0) > 100) {
    errors.ingredients = "성분 함유율 합계는 100%를 넘을 수 없습니다.";
  } else if (
    completedRows.length > 0
    && completedRows.filter((row) => row.role === "primary").length !== 1
  ) {
    errors.ingredients = "성분을 입력한 경우 주성분을 정확히 1개 지정하세요.";
  }

  const originCountry = clean(form.originCountry).toUpperCase();
  if (originCountry && !/^[A-Z]{2}$/.test(originCountry)) {
    errors.originCountry = "원산국은 KR, VN처럼 영문 2자리 코드로 입력하세요.";
  }
  if (
    form.intendedUse
    && !INTENDED_USE_OPTIONS.some(([value]) => value === form.intendedUse)
  ) {
    errors.intendedUse = "제공된 상품 용도 중 하나를 선택하세요.";
  }
  return errors;
}

function HasFormErrors(errors) {
  return Boolean(
    errors.ingredients
    || errors.originCountry
    || errors.intendedUse
    || Object.keys(errors.ingredientRows || {}).length,
  );
}

export function IngredientEditor({ rows, errors, onChange, onAdd, onRemove }) {
  return (
    <fieldset className="cjs-ingredient-fieldset">
      <legend>주·부성분</legend>
      <div className="cjs-field-heading">
        <small>완제품 기준 재료명과 함유율(%)을 입력하세요.</small>
        <button
          type="button"
          className="cjs-add-button"
          onClick={onAdd}
          disabled={rows.length >= 20}
          aria-label="성분 입력 행 추가"
        >
          + 성분 추가
        </button>
      </div>
      <div className="cjs-ingredient-labels" aria-hidden="true">
        <span>구분</span>
        <span>재료명</span>
        <span>함유율 (%)</span>
        <span />
      </div>
      {rows.map((row, index) => {
        const errorId = `cjs-ingredient-error-${index}`;
        return (
          <div className="cjs-ingredient-row-wrap" key={index}>
            <div className="cjs-ingredient-row">
              <select
                className="cjs-input"
                aria-label={`${index + 1}번째 성분 구분`}
                value={row.role}
                onChange={(event) => onChange(index, "role", event.target.value)}
              >
                <option value="primary">주성분</option>
                <option value="secondary">부성분</option>
              </select>
              <input
                type="text"
                className="cjs-input"
                aria-label={`${index + 1}번째 재료명`}
                aria-describedby={errors[index] ? errorId : undefined}
                placeholder="예: 낙지"
                value={row.name}
                onChange={(event) => onChange(index, "name", event.target.value)}
              />
              <input
                type="number"
                className="cjs-input"
                aria-label={`${index + 1}번째 함유율`}
                aria-describedby={errors[index] ? errorId : undefined}
                min="0.01"
                max="100"
                step="0.01"
                placeholder="예: 60"
                value={row.percentage}
                onChange={(event) => onChange(index, "percentage", event.target.value)}
              />
              <button
                type="button"
                className="cjs-remove-button"
                onClick={() => onRemove(index)}
                disabled={rows.length === 1}
                aria-label={`${index + 1}번째 성분 삭제`}
              >
                ×
              </button>
            </div>
            {errors[index] ? (
              <div id={errorId} className="cjs-field-error">{errors[index]}</div>
            ) : null}
          </div>
        );
      })}
    </fieldset>
  );
}

export default function ProductInputPanel({ busy, result, onRun, onRestore }) {
  const [form, setForm] = useState({
    productName: "",
    url: "",
    ingredients: [CreateIngredient("primary")],
    intendedUse: "",
    originCountry: "",
  });
  const [formErrors, setFormErrors] = useState({ ingredientRows: {} });
  const [jobIdInput, setJobIdInput] = useState("");
  const [loadError, setLoadError] = useState("");
  const [inputExpanded, setInputExpanded] = useState(true);

  useEffect(() => {
    if (clean(result?.job_id)) setJobIdInput(clean(result.job_id));
  }, [result?.job_id]);

  const SetField = (key) => (event) => {
    setFormErrors({ ingredientRows: {} });
    setForm((previous) => ({ ...previous, [key]: event.target.value }));
  };

  const SetIngredient = (index, key, value) => {
    setFormErrors({ ingredientRows: {} });
    setForm((previous) => ({
      ...previous,
      ingredients: previous.ingredients.map((item, itemIndex) => (
        itemIndex === index ? { ...item, [key]: value } : item
      )),
    }));
  };

  const AddIngredient = () => {
    setFormErrors({ ingredientRows: {} });
    setForm((previous) => ({
      ...previous,
      ingredients: [...previous.ingredients, CreateIngredient()],
    }));
  };

  const RemoveIngredient = (index) => {
    setFormErrors({ ingredientRows: {} });
    setForm((previous) => ({
      ...previous,
      ingredients: previous.ingredients.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  const Run = (mode) => {
    if (mode !== "reconstruct") {
      const nextErrors = ValidateStructuredInput(form);
      setFormErrors(nextErrors);
      if (HasFormErrors(nextErrors)) return;
    }
    setInputExpanded(false);
    onRun(mode, form);
  };

  const Restore = async () => {
    setLoadError("");
    try {
      await onRestore(jobIdInput);
      setInputExpanded(false);
    } catch (error) {
      setLoadError(String(error?.message || error));
    }
  };

  const requestFacts = asObject(result?.request?.facts);
  const inputSummaryName = clean(form.productName)
    || clean(requestFacts.product_name)
    || clean(requestFacts.product_id)
    || "상품 정보";
  const inputSummaryUrl = clean(form.url) || clean(requestFacts.url);

  return (
    <>
      <section className={`cjs-run-card ${inputExpanded ? "" : "collapsed"}`}>
        <div className="cjs-run-card-heading">
          <div>
            <strong>상품 입력</strong>
            <span>{inputExpanded ? "분류에 사용할 상품 정보와 확인된 보정값을 입력합니다." : "입력값이 요약되어 있습니다."}</span>
          </div>
          <button
            type="button"
            className="cjs-input-toggle"
            aria-expanded={inputExpanded}
            aria-controls="cjs-run-form"
            onClick={() => setInputExpanded((expanded) => !expanded)}
          >
            {inputExpanded ? "입력 접기" : "입력 정보 수정"}
          </button>
        </div>
        {inputExpanded ? (
          <div id="cjs-run-form" className="cjs-run-form">
            <div className="cjs-input-section-heading">
              <strong>기본 상품 정보</strong>
              <span>상품명 또는 URL 중 하나를 입력하세요.</span>
            </div>
            <div className="cjs-field">
              <label htmlFor="cjs-product-name">상품명</label>
              <input
                id="cjs-product-name"
                type="text"
                className="cjs-input"
                placeholder="예: 신라면, 낙지 볶음, 데오도란트"
                value={form.productName}
                onChange={SetField("productName")}
              />
            </div>
            <div className="cjs-field">
              <label htmlFor="cjs-product-url">상품 URL</label>
              <input
                id="cjs-product-url"
                type="text"
                className="cjs-input"
                placeholder="Kurly 또는 상품 상세 URL"
                value={form.url}
                onChange={SetField("url")}
              />
            </div>
            <div className="cjs-input-section-heading cjs-input-section-heading-secondary">
              <strong>분류 보정 정보</strong>
              <span>선택 입력 · 확인된 정보만 분류 근거에 반영됩니다.</span>
            </div>
            <div className="cjs-field cjs-field-full">
              <IngredientEditor
                rows={form.ingredients}
                errors={formErrors.ingredientRows || {}}
                onChange={SetIngredient}
                onAdd={AddIngredient}
                onRemove={RemoveIngredient}
              />
              {formErrors.ingredients ? (
                <div className="cjs-field-error">{formErrors.ingredients}</div>
              ) : null}
            </div>
            <div className="cjs-field">
              <label htmlFor="cjs-intended-use">상품 용도</label>
              <select
                id="cjs-intended-use"
                className="cjs-input"
                value={form.intendedUse}
                onChange={SetField("intendedUse")}
                aria-describedby={formErrors.intendedUse ? "cjs-intended-use-error" : "cjs-use-help"}
              >
                <option value="">선택하지 않음</option>
                {INTENDED_USE_OPTIONS.map(([value, label]) => (
                  <option value={value} key={value}>{label}</option>
                ))}
              </select>
              <small id="cjs-use-help">실제 사용 목적을 아는 경우에만 선택하세요.</small>
              {formErrors.intendedUse ? (
                <div id="cjs-intended-use-error" className="cjs-field-error">
                  {formErrors.intendedUse}
                </div>
              ) : null}
            </div>
            <div className="cjs-field cjs-origin-field">
              <label htmlFor="cjs-origin-country">상품 원산국</label>
              <input
                id="cjs-origin-country"
                type="text"
                className="cjs-input cjs-uppercase-input"
                maxLength="2"
                placeholder="예: KR, VN, CN, US"
                value={form.originCountry}
                onChange={SetField("originCountry")}
                aria-describedby={formErrors.originCountry ? "cjs-origin-error" : "cjs-origin-help"}
              />
              <small id="cjs-origin-help">원재료 산지가 아닌 완제품의 원산국입니다.</small>
              {formErrors.originCountry ? (
                <div id="cjs-origin-error" className="cjs-field-error">
                  {formErrors.originCountry}
                </div>
              ) : null}
            </div>
            <div className="cjs-run-actions">
              <Button type="button" variant="outline" size="lg" className="w-full sm:w-auto" disabled={busy} onClick={() => Run("cached")}>
                최근 입력으로 실행
              </Button>
              <Button type="button" variant="outline" size="lg" className="w-full sm:w-auto" disabled={busy} onClick={() => Run("reconstruct")}>
                상품 정보만 복원
              </Button>
              <Button type="button" size="lg" className="w-full sm:w-auto" disabled={busy} onClick={() => Run("full")}>
                분류 실행
              </Button>
            </div>
          </div>
        ) : (
          <div id="cjs-run-form" className="cjs-input-summary">
            <div>
              <span>분석 대상</span>
              <strong>{inputSummaryName}</strong>
              {inputSummaryUrl ? <small>{inputSummaryUrl}</small> : null}
            </div>
            <span>진행 상황과 결과를 아래에서 확인하세요.</span>
          </div>
        )}
      </section>

      <details className="cjs-run-restore" open>
        <summary>기존 작업 불러오기</summary>
        <div className="cjs-run-restore-body">
          <label htmlFor="cjs-job-id">작업 번호</label>
          <div className="cjs-run-restore-controls">
            <input
              id="cjs-job-id"
              type="text"
              className="cjs-input"
              placeholder="job_..."
              value={jobIdInput}
              onChange={(event) => setJobIdInput(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && Restore()}
              disabled={busy}
            />
            <Button type="button" variant="outline" size="lg" className="w-full sm:w-auto" disabled={busy} onClick={Restore}>
              불러오기
            </Button>
          </div>
          <small>백엔드에 남아 있는 job_id의 분류 후보와 TARIC 서류 패키지를 다시 엽니다.</small>
          {loadError ? <div className="cjs-run-restore-error">{loadError}</div> : null}
        </div>
      </details>
    </>
  );
}
