import assert from "node:assert/strict";
import test from "node:test";
import {
  BuildProductFormFromResult,
  CreateEmptyProductForm,
  GetIntendedUseLabel,
  HasProductInputErrors,
  ValidateProductRunInput,
} from "./classificationInput.js";

test("내부 상품 용도 값을 사용자 라벨로 바꾼다", () => {
  assert.equal(GetIntendedUseLabel("human consumption"), "최종 소비용");
  assert.equal(GetIntendedUseLabel("__none__", "선택하지 않음"), "선택하지 않음");
  assert.equal(GetIntendedUseLabel("_none_"), "미입력");
});

test("상품 정보 복원은 URL 또는 기존 product_id를 요구한다", () => {
  const form = { ...CreateEmptyProductForm(), productName: "상품명만 입력" };
  assert.equal(HasProductInputErrors(ValidateProductRunInput(form, "reconstruct", null)), true);

  form.url = "https://example.com/product/1";
  assert.equal(HasProductInputErrors(ValidateProductRunInput(form, "reconstruct", null)), false);
});

test("불러온 작업의 request facts를 입력 폼으로 복원한다", () => {
  const form = BuildProductFormFromResult({
    request: {
      facts: {
        product_name: "복원 상품",
        url: "https://example.com/product/2",
        user_input_facts: {
          ingredients: [{ role: "primary", name: "쌀", percentage: 80 }],
          intended_use: "human consumption",
          origin_country: "kr",
        },
      },
    },
  });
  assert.deepEqual(form, {
    productName: "복원 상품",
    url: "https://example.com/product/2",
    ingredients: [{ role: "primary", name: "쌀", percentage: "80" }],
    intendedUse: "human consumption",
    originCountry: "KR",
  });
});
