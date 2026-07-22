import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { importClassification } from "@/lib/enterpriseApi.js";
import { asList, asObject, clean } from "@/lib/format.js";

export default function DocumentRecommendationPanel({ result, viewModel }) {
  const navigate = useNavigate();
  const jobId = clean(result?.job_id || result?.run_id);
  const packages = Object.entries(viewModel.packagesByTaric);
  const [selectedTaric, setSelectedTaric] = useState("");
  const [savingProject, setSavingProject] = useState(false);
  const [projectError, setProjectError] = useState("");

  useEffect(() => {
    setSelectedTaric("");
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
    <div className="cjs-panel">
      <div className="cjs-panel-title">
        DocumentRecommendationPipeline · 서류 검토 패키지 ({packages.length}건)
      </div>
      <div className="cjs-note">
        TARIC10 분기별 서류 후보입니다. 필수 여부는 목적지·원산지·제품 사실과 공식 근거를 추가 확인해야 합니다.
      </div>
      {packages.length ? (
        <div className="cjs-taric-list">
          {packages.map(([taric, group]) => {
            const groupedPackages = asList(group);
            const documentCount = groupedPackages.reduce(
              (sum, item) => sum + Number(asObject(item).required_document_count || 0),
              0,
            );
            const missingCount = groupedPackages.reduce(
              (sum, item) => sum + asList(asObject(item).missing_facts).length,
              0,
            );
            return (
              <div className={`cjs-taric-row ${selectedTaric === taric ? "selected" : ""}`} key={taric}>
                <label className="cjs-taric-choice">
                  <input
                    type="radio"
                    name="document-project-package"
                    value={taric}
                    checked={selectedTaric === taric}
                    onChange={() => setSelectedTaric(taric)}
                  />
                  <span className="cjs-taric-copy">
                    <strong>{taric}</strong>
                    <small>서류 후보 {documentCount}건 · 추가 확인 {missingCount}건</small>
                  </span>
                </label>
                <Link
                  className="cjs-taric-detail-link"
                  to={`/document/${encodeURIComponent(jobId)}/${encodeURIComponent(taric)}`}
                >
                  상세 보기
                </Link>
              </div>
            );
          })}
          <div className="cjs-project-add-row">
            <span>
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
              {savingProject ? "추가 중…" : "프로젝트에 추가하기"}
            </Button>
          </div>
          {projectError ? <div className="cjs-note error" role="alert">{projectError}</div> : null}
        </div>
      ) : (
        <div className="cjs-muted">생성된 서류 패키지가 없습니다.</div>
      )}
    </div>
  );
}
