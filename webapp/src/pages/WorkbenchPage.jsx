import { useEffect, useMemo, useRef, useState } from "react";
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
  GetPipelineStageState,
  useClassificationViewModel,
} from "@/features/classification/model/classificationViewModel.js";
import { useClassificationRun } from "@/hooks/useClassificationRun";
import { ClassificationStepForResult, STAGES } from "@/lib/labels.js";
import { candidateKey, clean } from "@/lib/format.js";
import { extractTrace } from "@/lib/traceContract.js";

export default function WorkbenchPage() {
  const [searchParams] = useSearchParams();
  const { result, busy, runPipeline, loadRun } = useClassificationRun(searchParams.get("job"));
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
    if (busy) {
      followStageRef.current = true;
      followClassificationRef.current = true;
    }
  }, [busy]);

  useEffect(() => {
    if (!followStageRef.current) return;
    const status = clean(result?.job_status).toLowerCase();
    if (["completed", "complete", "done"].includes(status)) {
      setActiveStage("classification");
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
    await loadRun(jobId);
    followStageRef.current = true;
  };

  const defaultCandidate = viewModel.candidates.find((candidate) => candidate.llm_recommended)
    || viewModel.candidates[0]
    || null;
  const selectedCandidate = viewModel.candidates.find(
    (candidate, index) => candidateKey(candidate, index) === selectedKey,
  ) || defaultCandidate;

  return (
    <div className="classification-js-shell">
      <WorkspaceHeader
        eyebrow="ASAP Classification"
        title="EU 수출 품목분류"
        description="상품 정보를 읽고 HS6/CN8 후보와 TARIC10 서류 연결 지점을 확인합니다."
        badge="분류 워크스페이스"
      />

      <ProductInputPanel
        busy={busy}
        result={result}
        onRun={runPipeline}
        onRestore={RestoreRun}
      />

      <section className="cjs-workspace cjs-workspace-nav">
        <PipelineStageRail
          result={result}
          viewModel={viewModel}
          activeStage={activeStage}
          onSelect={PickStage}
          busy={busy}
        />
        <main className="cjs-stage-content">
          {activeStage === "product_collection" ? (
            <ProductCollectionPanel result={result} />
          ) : null}
          {activeStage === "classification" ? (
            <>
              <ClassificationStageHeader
                activeStep={classificationStep}
                onSelect={PickClassificationStep}
              />
              <div className="cjs-classification-step-content">
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
                  />
                ) : null}
                {classificationStep === "review" ? (
                  <>
                    <TariffCandidateList
                      candidates={viewModel.candidates}
                      selectedKey={selectedKey}
                      onSelect={setSelectedKey}
                    />
                    <ClassificationEvidencePanel candidate={selectedCandidate} trace={trace} />
                  </>
                ) : null}
              </div>
              <ClassificationPager
                activeStep={classificationStep}
                onSelect={PickClassificationStep}
              />
            </>
          ) : null}
          {activeStage === "document_recommendation" ? (
            <DocumentRecommendationPanel result={result} viewModel={viewModel} />
          ) : null}
        </main>
      </section>
    </div>
  );
}
