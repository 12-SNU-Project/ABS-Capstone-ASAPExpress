import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useSearchParams } from "react-router-dom";
import WorkspaceHeader from "@/components/layout/WorkspaceHeader";
import {
  ClassificationPager,
  ClassificationStageHeader,
} from "@/features/classification/components/ClassificationNavigation";
import {
  ClassificationEvidencePanel,
  ClassificationHierarchy,
} from "@/features/classification/components/ClassificationReviewPanels";
import DocumentRecommendationPanel from "@/features/classification/components/DocumentRecommendationPanel";
import PipelineStageRail from "@/features/classification/components/PipelineStageRail";
import ProductInputPanel from "@/features/classification/components/ProductInputPanel";
import {
  ProductCollectionPanel,
  ProductUnderstandingPanel,
} from "@/features/classification/components/ProductEvidencePanels";
import TariffCandidateList from "@/features/classification/components/TariffCandidateList";
import TariffRoutingPanel from "@/features/classification/components/TariffRoutingPanel";
import {
  CompletedPipelineStage,
  GetPipelineStageState,
  useClassificationViewModel,
} from "@/features/classification/model/classificationViewModel.js";
import { useClassificationRun } from "@/hooks/useClassificationRun";
import { ClassificationStepForResult, STAGES } from "@/lib/labels.js";
import { candidateKey, clean } from "@/lib/format.js";
import { extractTrace } from "@/lib/traceContract.js";

export default function WorkbenchPage() {
  const reduceMotion = useReducedMotion();
  const [searchParams, setSearchParams] = useSearchParams();
  const jobQuery = clean(searchParams.get("job"));
  const {
    result,
    busy,
    restoring,
    restorableJobId,
    runPipeline,
    loadRun,
  } = useClassificationRun(jobQuery);
  const [selectedKey, setSelectedKey] = useState("");
  const [activeStage, setActiveStage] = useState("classification");
  const [classificationStep, setClassificationStep] = useState("understanding");
  const followStageRef = useRef(true);
  const followClassificationRef = useRef(true);
  const viewModel = useClassificationViewModel(result);
  const trace = useMemo(
    () => extractTrace(viewModel.candidateSet),
    [viewModel.candidateSet],
  );

  useEffect(() => {
    if (!restorableJobId || jobQuery === restorableJobId) return;
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("job", restorableJobId);
    setSearchParams(nextParams, { replace: true });
  }, [jobQuery, restorableJobId, searchParams, setSearchParams]);

  useEffect(() => {
    if (busy) {
      followStageRef.current = true;
      followClassificationRef.current = true;
    }
  }, [busy]);

  useEffect(() => {
    if (!followStageRef.current) return;
    const status = clean(result?.job_status).toLowerCase();
    if (["completed", "complete", "done"].includes(status)) {
      setActiveStage(CompletedPipelineStage(result));
      return;
    }
    let latest = "product_collection";
    STAGES.forEach(([key]) => {
      const state = GetPipelineStageState(result, viewModel, key);
      if (["done", "running", "completed"].includes(state)) latest = key;
    });
    setActiveStage(latest);
  }, [result, viewModel, busy]);

  useEffect(() => {
    if (followClassificationRef.current) {
      setClassificationStep(ClassificationStepForResult(result));
    }
  }, [result]);

  const PickStage = (key) => {
    followStageRef.current = false;
    setActiveStage(key);
  };

  const PickClassificationStep = (key) => {
    followClassificationRef.current = false;
    setClassificationStep(key);
  };

  const RestoreRun = async (jobId) => {
    const snapshot = await loadRun(jobId);
    followStageRef.current = true;
    return snapshot;
  };

  const defaultCandidate = viewModel.candidates.find((candidate) => candidate.llm_recommended)
    || viewModel.candidates[0]
    || null;
  const selectedCandidate = viewModel.candidates.find(
    (candidate, index) => candidateKey(candidate, index) === selectedKey,
  ) || defaultCandidate;
  const resultStatus = clean(result?.job_status).toLowerCase();
  const hasRun = Boolean(
    restoring
    || clean(result?.job_id)
    || result?.error
    || ["submitting", "queued", "running", "completed", "complete", "done"].includes(resultStatus)
    || result?.input_processing_view
    || viewModel.candidates.length,
  );

  return (
    <div className="classification-js-shell grid min-w-0 gap-4">
      <WorkspaceHeader
        eyebrow="ASAP Classification"
        title="EU 수출 품목분류"
        description="상품 정보를 읽고 HS6/CN8 후보와 TARIC10 서류 연결 지점을 확인합니다."
        badge="분류 워크스페이스"
      />

      <div className={hasRun ? "grid min-w-0 gap-4 lg:grid-cols-[minmax(250px,300px)_minmax(0,1fr)]" : "mx-auto w-full max-w-[1040px]"}>
        <ProductInputPanel
          busy={busy}
          result={result}
          onRun={runPipeline}
          onRestore={RestoreRun}
          compact={hasRun}
        />

        {hasRun ? (
          <section className="grid min-w-0 content-start gap-4">
            <PipelineStageRail
              result={result}
              viewModel={viewModel}
              activeStage={activeStage}
              onSelect={PickStage}
              busy={busy}
              restoring={restoring}
            />
            <main className="grid min-w-0 content-start gap-4">
          {restoring ? (
            <div className="rounded-xl border bg-surface p-6 text-sm text-muted-foreground" role="status">
              저장된 snapshot과 현재 실행 상태를 동기화하는 중입니다.
            </div>
          ) : (
            <>
          {activeStage === "product_collection" ? (
            <ProductCollectionPanel result={result} />
          ) : null}
          {activeStage === "classification" ? (
            <>
              <ClassificationStageHeader
                activeStep={classificationStep}
                onSelect={PickClassificationStep}
              />
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={classificationStep}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: reduceMotion ? 0 : 0.18, ease: "easeOut" }}
                  className="grid min-w-0 gap-4"
                >
                {classificationStep === "understanding" ? (
                  <ProductUnderstandingPanel result={result} />
                ) : null}
                {classificationStep === "routing" ? (
                  <TariffRoutingPanel result={result} />
                ) : null}
                {classificationStep === "hierarchy" ? (
                  <ClassificationHierarchy
                    candidates={viewModel.candidates}
                    selectedPath={viewModel.candidateSet.selected_path}
                    selectedCn8={selectedCandidate?.cn8}
                  />
                ) : null}
                {classificationStep === "review" ? (
                  <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(280px,340px)_minmax(0,1fr)]">
                    <TariffCandidateList
                      candidates={viewModel.candidates}
                      selectedKey={selectedKey}
                      onSelect={setSelectedKey}
                    />
                    <ClassificationEvidencePanel candidate={selectedCandidate} trace={trace} />
                  </div>
                ) : null}
                </motion.div>
              </AnimatePresence>
              <div className="md:hidden">
                <ClassificationPager activeStep={classificationStep} onSelect={PickClassificationStep} />
              </div>
            </>
          ) : null}
          {activeStage === "document_recommendation" ? (
            <DocumentRecommendationPanel
              result={result}
              viewModel={viewModel}
              selectedCandidate={selectedCandidate}
            />
          ) : null}
            </>
          )}
            </main>
          </section>
        ) : null}
      </div>
    </div>
  );
}
