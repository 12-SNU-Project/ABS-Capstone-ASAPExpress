import { useEffect, useState } from "react";
import { FileSearch, FolderPlus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  BuildDocumentPackageOptions,
  PrioritizeRecommendedDocumentPackage,
  ResolveDocumentPackageSelection,
} from "@/features/classification/model/classificationViewModel.js";
import { importClassification } from "@/lib/enterpriseApi.js";
import { asList, asObject, clean } from "@/lib/format.js";
import { cn } from "@/lib/utils";

function PackageSummary(group) {
  const packages = asList(group);
  const primary = asObject(packages[0]);
  const counts = asObject(asObject(primary.checklist_summary).counts);
  const cards = packages.flatMap((item) => asList(asObject(asObject(item).checklist_summary).document_binding_cards));
  const basicCount = Number(counts.required || cards.filter((card) => ["required", "mandatory"].includes(clean(asObject(card).required_level))).length);
  const conditionalCount = Number(counts.conditional || cards.filter((card) => clean(asObject(card).required_level) === "conditional").length);
  const unresolved = new Set(packages.flatMap((item) => [
    ...asList(asObject(item).missing_facts),
    ...asList(asObject(asObject(item).summary).unknowns),
  ].map(clean).filter(Boolean)));
  return { basicCount, conditionalCount, unresolvedCount: unresolved.size };
}

const MATCH_LABELS = {
  taric10: "TARIC10 일치",
  cn8: "CN8 일치",
  hs6: "HS6 일치",
  branch: "선택 후보 Branch",
};

export default function DocumentRecommendationPanel({ result, viewModel, selectedCandidate }) {
  const navigate = useNavigate();
  const jobId = clean(result?.job_id || result?.run_id);
  const packages = BuildDocumentPackageOptions(viewModel.packagesByTaric, selectedCandidate);
  const [packageSelection, setPackageSelection] = useState({
    jobId: "",
    taric: "",
    manual: false,
  });
  const [savingProject, setSavingProject] = useState(false);
  const [projectError, setProjectError] = useState("");
  const currentSelection = packageSelection.jobId === jobId
    ? packageSelection
    : { taric: "", manual: false };
  const resolvedSelection = ResolveDocumentPackageSelection(packages, currentSelection);
  const selectedTaric = resolvedSelection.taric;
  const recommendedTaric = ResolveDocumentPackageSelection(packages).taric;
  const displayPackages = PrioritizeRecommendedDocumentPackage(
    packages,
    recommendedTaric,
  );

  useEffect(() => {
    setProjectError("");
  }, [jobId]);

  const AddSelectedPackageToProject = async () => {
    if (!jobId || !selectedTaric || savingProject) return;
    setSavingProject(true);
    setProjectError("");
    try {
      const response = await importClassification({ jobId, taric10: selectedTaric });
      if (!response?.caseId) throw new Error("프로젝트 생성 결과를 확인할 수 없습니다.");
      navigate(`/enterprise?caseId=${encodeURIComponent(response.caseId)}&panel=docs`);
    } catch (error) {
      setProjectError(String(error?.message || error));
    } finally {
      setSavingProject(false);
    }
  };

  return (
    <section className="min-w-0 rounded-xl border bg-surface shadow-[var(--shadow-surface)]">
      <div className="border-b px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="m-0 text-base font-semibold">선택 후보의 TARIC Branch</h2>
          <Badge variant="secondary">Branch {packages.length}건</Badge>
        </div>
        <p className="mt-1.5 mb-0 max-w-3xl text-sm leading-6 text-muted-foreground">
          결과 검토에서 선택한 분류 후보에 연결된 Branch별 서류와 미해결 사실을 비교합니다.
        </p>
      </div>
      {packages.length ? (
        <div className="divide-y">
          {displayPackages.map(({ taric, group, matchLevel }) => {
            const summary = PackageSummary(group);
            const selected = selectedTaric === taric;
            const originalIndex = packages.findIndex((option) => option.taric === taric);
            const branchIndex = Number(asObject(asList(group)[0]).taric10_branch_index)
              || originalIndex + 1;
            return (
              <article className={`grid gap-3 px-4 py-4 transition-colors sm:grid-cols-[minmax(180px,1.3fr)_repeat(4,minmax(90px,0.7fr))_auto] sm:items-center sm:px-5 ${selected ? "bg-primary/5" : "hover:bg-muted/50"}`} key={taric}>
                <label className="flex min-w-0 cursor-pointer items-center gap-3">
                  <input
                    type="radio"
                    className="size-4 accent-primary"
                    name="document-project-package"
                    value={taric}
                    checked={selectedTaric === taric}
                    onChange={() => setPackageSelection({ jobId, taric, manual: true })}
                    onClick={() => setPackageSelection({ jobId, taric, manual: true })}
                  />
                  <span className="min-w-0">
                    <small className="block text-xs text-muted-foreground">Branch {branchIndex} / {packages.length}</small>
                    <strong className="block truncate font-mono text-base">{taric}</strong>
                    <Badge className="mt-1" variant="secondary">
                      {MATCH_LABELS[matchLevel] || "선택 후보"}
                    </Badge>
                  </span>
                </label>
                <span><small className="block text-xs text-muted-foreground">기본 서류</small><strong className="text-sm">{summary.basicCount}건</strong></span>
                <span><small className="block text-xs text-muted-foreground">조건부 서류</small><strong className="text-sm">{summary.conditionalCount}건</strong></span>
                <span><small className="block text-xs text-muted-foreground">미해결 사실</small><strong className={summary.unresolvedCount ? "text-sm text-needs-review" : "text-sm text-success"}>{summary.unresolvedCount}건</strong></span>
                <span><small className="block text-xs text-muted-foreground">선택 상태</small><strong className="text-sm">{selected ? "선택됨" : "미선택"}</strong></span>
                <Link
                  className={cn(buttonVariants({ variant: "outline" }), "gap-1.5")}
                  to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(taric)}`}
                >
                  <FileSearch aria-hidden="true" /> 상세 보기
                </Link>
              </article>
            );
          })}
          <div className="flex flex-col gap-3 bg-surface-muted px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <span className="text-sm text-muted-foreground">
              {selectedTaric
                ? `TARIC10 ${selectedTaric} 서류 패키지를 프로젝트로 등록합니다.`
                : "프로젝트로 등록할 TARIC10 후보를 하나 선택하세요."}
            </span>
            <Button
              type="button"
              size="lg"
              className="w-full shrink-0 sm:w-auto"
              disabled={!jobId || !selectedTaric || savingProject}
              onClick={AddSelectedPackageToProject}
            >
              <FolderPlus aria-hidden="true" />
              {savingProject ? "추가 중…" : "프로젝트에 추가하기"}
            </Button>
          </div>
          {projectError ? <div className="border-t border-destructive/20 bg-destructive/5 px-5 py-3 text-sm text-destructive" role="alert">{projectError}</div> : null}
        </div>
      ) : (
        <div className="p-8 text-center text-sm text-muted-foreground">
          {selectedCandidate
            ? "선택 후보에 연결된 서류 Branch가 없습니다."
            : "결과 검토에서 분류 후보를 먼저 선택하세요."}
        </div>
      )}
    </section>
  );
}
