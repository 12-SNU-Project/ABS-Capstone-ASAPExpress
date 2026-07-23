import { useEffect, useState } from "react";
import { PencilLine, Plus, Trash2 } from "lucide-react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { asObject, clean } from "@/lib/format.js";
import {
  BuildProductFormFromResult,
  CreateEmptyProductForm,
  CreateIngredient,
  HasProductInputErrors,
  INTENDED_USE_OPTIONS,
  ValidateProductRunInput,
} from "@/features/classification/model/classificationInput.js";

function FieldError({ id, children }) {
  if (!children) return null;
  return <p id={id} className="m-0 text-xs font-medium text-destructive" role="alert">{children}</p>;
}

export function IngredientEditor({ rows, errors, onChange, onAdd, onRemove }) {
  return (
    <fieldset className="min-w-0 border-0 p-0">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <legend className="text-sm font-semibold text-foreground">주·부성분</legend>
          <p className="mt-1 mb-0 text-xs leading-5 text-muted-foreground">
            확인된 재료명과 완제품 기준 함유율만 입력하세요.
          </p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onAdd} disabled={rows.length >= 20}>
          <Plus data-icon="inline-start" /> 성분 추가
        </Button>
      </div>
      <div className="hidden grid-cols-[120px_minmax(0,1fr)_120px_36px] gap-2 px-1 pb-2 text-xs font-medium text-muted-foreground sm:grid" aria-hidden="true">
        <span>구분</span><span>재료명</span><span>함유율 (%)</span><span />
      </div>
      <div className="divide-y rounded-lg border bg-surface">
        {rows.map((row, index) => {
          const errorId = `ingredient-error-${index}`;
          return (
            <div className="grid gap-2 p-3" key={index}>
              <div className="grid min-w-0 gap-2 sm:grid-cols-[120px_minmax(0,1fr)_120px_36px]">
                <Select value={row.role} onValueChange={(value) => onChange(index, "role", value)}>
                  <SelectTrigger className="h-10 w-full" aria-label={`${index + 1}번째 성분 구분`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="primary">주성분</SelectItem>
                    <SelectItem value="secondary">부성분</SelectItem>
                  </SelectContent>
                </Select>
                <Input
                  className="h-10"
                  aria-label={`${index + 1}번째 재료명`}
                  aria-describedby={errors[index] ? errorId : undefined}
                  aria-invalid={Boolean(errors[index])}
                  placeholder="예: 낙지"
                  value={row.name}
                  onChange={(event) => onChange(index, "name", event.target.value)}
                />
                <Input
                  type="number"
                  className="h-10"
                  aria-label={`${index + 1}번째 함유율`}
                  aria-describedby={errors[index] ? errorId : undefined}
                  aria-invalid={Boolean(errors[index])}
                  min="0.01"
                  max="100"
                  step="0.01"
                  placeholder="예: 60"
                  value={row.percentage}
                  onChange={(event) => onChange(index, "percentage", event.target.value)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-lg"
                  onClick={() => onRemove(index)}
                  disabled={rows.length === 1}
                  aria-label={`${index + 1}번째 성분 삭제`}
                >
                  <Trash2 />
                </Button>
              </div>
              <FieldError id={errorId}>{errors[index]}</FieldError>
            </div>
          );
        })}
      </div>
    </fieldset>
  );
}

function ProductSourceFields({ form, errors, onFieldChange }) {
  return (
    <section className="grid gap-4">
      <div>
        <h3 className="m-0 text-base font-semibold">상품 출처</h3>
        <p className="mt-1 mb-0 text-sm text-muted-foreground">상품명 또는 상품 상세 URL이 필요합니다.</p>
      </div>
      <FieldError>{errors.productSource}</FieldError>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="grid gap-2 text-sm font-medium" htmlFor="product-name">
          상품명
          <Input
            id="product-name"
            className="h-10"
            placeholder="예: 신라면, 낙지 볶음"
            value={form.productName}
            onChange={onFieldChange("productName")}
          />
        </label>
        <label className="grid gap-2 text-sm font-medium" htmlFor="product-url">
          상품 URL
          <Input
            id="product-url"
            type="url"
            className="h-10"
            placeholder="https://..."
            value={form.url}
            onChange={onFieldChange("url")}
            aria-invalid={Boolean(errors.url)}
            aria-describedby={errors.url ? "product-url-error" : undefined}
          />
          <FieldError id="product-url-error">{errors.url}</FieldError>
        </label>
      </div>
    </section>
  );
}

function TradeContextFields({ form, errors, onFieldChange, ingredientProps }) {
  return (
    <section className="grid gap-5 border-t pt-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="m-0 text-base font-semibold">분류 보정 정보</h3>
          <Badge variant="outline">선택 입력</Badge>
        </div>
        <p className="mt-1 mb-0 text-sm text-muted-foreground">사용자가 확인한 사실만 분류 근거에 반영됩니다.</p>
      </div>
      <IngredientEditor {...ingredientProps} />
      <FieldError>{errors.ingredients}</FieldError>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid gap-2">
          <label className="text-sm font-medium" htmlFor="intended-use">상품 용도</label>
          <Select value={form.intendedUse || "__none__"} onValueChange={(value) => onFieldChange("intendedUse")({ target: { value: value === "__none__" ? "" : value } })}>
            <SelectTrigger id="intended-use" className="h-10 w-full" aria-invalid={Boolean(errors.intendedUse)}>
              <SelectValue placeholder="선택하지 않음" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">선택하지 않음</SelectItem>
              {INTENDED_USE_OPTIONS.map(([value, label]) => (
                <SelectItem value={value} key={value}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="m-0 text-xs text-muted-foreground">실제 사용 목적을 아는 경우에만 선택하세요.</p>
          <FieldError>{errors.intendedUse}</FieldError>
        </div>
        <label className="grid gap-2 text-sm font-medium" htmlFor="origin-country">
          상품 원산국
          <Input
            id="origin-country"
            className="h-10 uppercase"
            maxLength="2"
            placeholder="예: KR, VN, CN"
            value={form.originCountry}
            onChange={onFieldChange("originCountry")}
            aria-invalid={Boolean(errors.originCountry)}
          />
          <span className="text-xs font-normal text-muted-foreground">원재료 산지가 아닌 완제품의 원산국입니다.</span>
          <FieldError>{errors.originCountry}</FieldError>
        </label>
      </div>
    </section>
  );
}

function RunActionBar({ busy, onRun }) {
  return (
    <div className="grid gap-2 border-t pt-5 sm:grid-cols-3">
      <Button type="button" variant="outline" size="lg" disabled={busy} onClick={() => onRun("cached")}>최근 입력으로 실행</Button>
      <Button type="button" variant="outline" size="lg" disabled={busy} onClick={() => onRun("reconstruct")}>상품 정보만 복원</Button>
      <Button type="button" size="lg" disabled={busy} onClick={() => onRun("full")}>분류 실행</Button>
    </div>
  );
}

function JobRestore({ busy, jobIdInput, loadError, onJobIdChange, onRestore }) {
  return (
    <Accordion defaultValue={["restore"]} className="border-t">
      <AccordionItem value="restore" className="border-0">
        <AccordionTrigger className="py-4 hover:no-underline">기존 작업 불러오기</AccordionTrigger>
        <AccordionContent className="grid gap-2 pb-1">
          <label className="text-sm font-medium" htmlFor="job-id">작업 번호</label>
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
            <Input
              id="job-id"
              className="h-10"
              placeholder="job_..."
              value={jobIdInput}
              onChange={(event) => onJobIdChange(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && onRestore()}
              disabled={busy}
            />
            <Button type="button" variant="outline" size="lg" disabled={busy} onClick={onRestore}>불러오기</Button>
          </div>
          <p className="m-0 text-xs leading-5 text-muted-foreground">백엔드에 남아 있는 작업 번호의 snapshot과 진행 중 SSE를 다시 연결합니다.</p>
          <FieldError>{loadError}</FieldError>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}

function ProductInputSummary({ form, requestFacts, jobId, onEdit }) {
  const userInputFacts = asObject(requestFacts.user_input_facts);
  const intendedUse = clean(userInputFacts.intended_use || form.intendedUse);
  const intendedUseLabel = INTENDED_USE_OPTIONS.find(([value]) => value === intendedUse)?.[1] || "미입력";
  const origin = clean(userInputFacts.origin_country || form.originCountry) || "미입력";
  const ingredients = form.ingredients.filter((item) => clean(item.name));
  const primaryIngredients = ingredients.filter((item) => item.role === "primary");
  const productName = clean(requestFacts.product_name || requestFacts.product_id || form.productName) || "상품명 미입력";
  const sourceUrl = clean(requestFacts.url || form.url);

  return (
    <Card className="gap-0 self-start py-0 shadow-[var(--shadow-surface)] lg:sticky lg:top-20">
      <CardHeader className="border-b py-4">
        <div className="flex items-center justify-between gap-3">
          <Badge variant="secondary">분석 대상</Badge>
          <Button type="button" variant="ghost" size="sm" onClick={onEdit}><PencilLine /> 입력 수정</Button>
        </div>
        <CardTitle className="mt-3 text-lg">{productName}</CardTitle>
        <CardDescription className="line-clamp-3 break-all">{sourceUrl || "상품 URL 미입력"}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-0 px-4 py-2 text-sm">
        {[
          ["원산국", origin],
          ["상품 용도", intendedUseLabel],
          ["주성분", primaryIngredients.map((item) => item.name).join(", ") || "미입력"],
          ["입력 성분", ingredients.length ? `${ingredients.length}건` : "미입력"],
          ["작업 번호", jobId || "등록 중"],
        ].map(([label, value]) => (
          <div className="grid grid-cols-[74px_minmax(0,1fr)] gap-3 border-b py-3 last:border-0" key={label}>
            <span className="text-xs font-medium text-muted-foreground">{label}</span>
            <strong className="min-w-0 break-words text-sm font-medium">{value}</strong>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export default function ProductInputPanel({
  busy,
  result,
  restoreError,
  onRun,
  onRestore,
  compact = false,
}) {
  const [form, setForm] = useState(CreateEmptyProductForm);
  const [formErrors, setFormErrors] = useState({ ingredientRows: {} });
  const [jobIdInput, setJobIdInput] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const resultJobId = clean(result?.job_id);
  const requestFacts = asObject(result?.request?.facts);

  useEffect(() => {
    if (!resultJobId || resultJobId.startsWith("reconstruct_")) return;
    setJobIdInput(resultJobId);
    const restoredForm = BuildProductFormFromResult(result);
    if (restoredForm) setForm(restoredForm);
  }, [resultJobId, result?.request?.facts]);

  useEffect(() => {
    if (compact && clean(result?.job_status).toLowerCase() === "failed") setEditorOpen(true);
  }, [compact, result?.job_status]);

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
    setForm((previous) => ({ ...previous, ingredients: [...previous.ingredients, CreateIngredient()] }));
  };
  const RemoveIngredient = (index) => {
    setFormErrors({ ingredientRows: {} });
    setForm((previous) => ({
      ...previous,
      ingredients: previous.ingredients.filter((_, itemIndex) => itemIndex !== index),
    }));
  };
  const Run = (mode) => {
    const nextErrors = ValidateProductRunInput(form, mode, result);
    setFormErrors(nextErrors);
    if (HasProductInputErrors(nextErrors)) return;
    setEditorOpen(false);
    onRun(mode, form);
  };
  const Restore = async () => {
    const restored = await onRestore(jobIdInput);
    if (restored) setEditorOpen(false);
  };
  const formContent = (
    <div className="grid gap-5">
      <ProductSourceFields form={form} errors={formErrors} onFieldChange={SetField} />
      <TradeContextFields
        form={form}
        errors={formErrors}
        onFieldChange={SetField}
        ingredientProps={{
          rows: form.ingredients,
          errors: formErrors.ingredientRows || {},
          onChange: SetIngredient,
          onAdd: AddIngredient,
          onRemove: RemoveIngredient,
        }}
      />
      <RunActionBar busy={busy} onRun={Run} />
      <JobRestore busy={busy} jobIdInput={jobIdInput} loadError={restoreError} onJobIdChange={setJobIdInput} onRestore={Restore} />
    </div>
  );

  if (!compact) {
    return (
      <Card className="mx-auto w-full max-w-[1000px] shadow-[var(--shadow-surface)]">
        <CardHeader className="border-b">
          <CardTitle className="text-xl">상품 정보 입력</CardTitle>
          <CardDescription>상품 출처와 확인된 분류 보정 정보를 입력해 분석을 시작합니다.</CardDescription>
        </CardHeader>
        <CardContent>{formContent}</CardContent>
      </Card>
    );
  }

  return (
    <Sheet open={editorOpen} onOpenChange={setEditorOpen}>
      <ProductInputSummary form={form} requestFacts={requestFacts} jobId={resultJobId} onEdit={() => setEditorOpen(true)} />
      <SheetContent className="w-full overflow-y-auto sm:max-w-[540px]">
        <SheetHeader className="border-b pr-14">
          <SheetTitle>상품 입력 수정</SheetTitle>
          <SheetDescription>수정한 입력으로 복원 또는 전체 분류를 다시 실행할 수 있습니다.</SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6">{formContent}</div>
      </SheetContent>
    </Sheet>
  );
}
