import { asList, asObject, clean } from "../../../lib/format.js";

export const INTENDED_USE_OPTIONS = [
  ["human consumption", "최종 소비용"],
  ["further processing", "추가 가공용"],
  ["animal feed", "동물 사료용"],
  ["non-food use", "비식품용"],
];

export function GetIntendedUseLabel(value, emptyLabel = "미입력") {
  const normalized = clean(value);
  if (!normalized || ["__none__", "_none_", "none"].includes(normalized.toLowerCase())) {
    return emptyLabel;
  }
  return INTENDED_USE_OPTIONS.find(([option]) => option === normalized)?.[1] || normalized;
}

export function CreateIngredient(role = "secondary") {
  return { role, name: "", percentage: "" };
}

export function CreateEmptyProductForm() {
  return {
    productName: "",
    url: "",
    ingredients: [CreateIngredient("primary")],
    intendedUse: "",
    originCountry: "",
  };
}

function ValidateStructuredFacts(form, errors) {
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
}

function HasHttpUrl(value) {
  const url = clean(value);
  if (!url) return true;
  try {
    return ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

export function ValidateProductRunInput(form, mode, result) {
  const errors = { ingredientRows: {} };
  const productName = clean(form.productName);
  const url = clean(form.url);
  const previousFacts = asObject(result?.request?.facts);

  if (url && !HasHttpUrl(url)) {
    errors.url = "상품 URL은 http:// 또는 https://로 시작하는 전체 주소를 입력하세요.";
  }
  if (mode === "reconstruct") {
    if (!url && !clean(previousFacts.product_id)) {
      errors.productSource = "상품 정보 복원에는 상품 URL 또는 기존 작업의 product_id가 필요합니다.";
    }
    return errors;
  }

  ValidateStructuredFacts(form, errors);
  const cachedSource = clean(previousFacts.product_id) || clean(previousFacts.product_name);
  if (!productName && !url && !(mode === "cached" && cachedSource)) {
    errors.productSource = "상품명 또는 상품 URL 중 하나를 입력하세요.";
  }
  return errors;
}

export function HasProductInputErrors(errors) {
  return Boolean(
    errors.productSource
    || errors.url
    || errors.ingredients
    || errors.originCountry
    || errors.intendedUse
    || Object.keys(errors.ingredientRows || {}).length,
  );
}

export function BuildProductFormFromResult(result) {
  const facts = asObject(result?.request?.facts);
  if (!Object.keys(facts).length) return null;
  const userInput = asObject(facts.user_input_facts);
  const ingredientFacts = asList(userInput.ingredients).length
    ? asList(userInput.ingredients)
    : asList(facts.ingredients);
  const ingredients = ingredientFacts
    .map(asObject)
    .filter((item) => clean(item.name) || clean(item.percentage))
    .map((item, index) => ({
      role: item.role === "primary" ? "primary" : "secondary",
      name: clean(item.name),
      percentage: clean(item.percentage),
      ...(index === 0 && !clean(item.role) ? { role: "primary" } : {}),
    }));
  return {
    productName: clean(facts.product_name),
    url: clean(facts.url),
    ingredients: ingredients.length ? ingredients : [CreateIngredient("primary")],
    intendedUse: clean(userInput.intended_use || facts.intended_use),
    originCountry: clean(userInput.origin_country || facts.origin_country).toUpperCase(),
  };
}
