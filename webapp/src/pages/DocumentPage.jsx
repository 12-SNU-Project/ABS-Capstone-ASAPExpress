import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import DocumentPackageDetail from "@/components/DocumentPackageDetail";
import WorkspaceHeader from "@/components/layout/WorkspaceHeader";
import { importClassification } from "@/lib/enterpriseApi.js";
import { getJson } from "@/lib/api.js";
import { asList, clean } from "@/lib/format.js";

export default function DocumentPage() {
  const { jobId, taric10 } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const caseId = clean(searchParams.get("caseId"));
  const returnTarget = caseId
    ? `/enterprise?caseId=${encodeURIComponent(caseId)}&panel=docs`
    : `/classification?job=${encodeURIComponent(jobId)}`;
  const [packages, setPackages] = useState([]);
  const [packageData, setPackageData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const PackagePath = (target) => (
    `/document/${encodeURIComponent(jobId)}/${encodeURIComponent(target)}${caseId ? `?caseId=${encodeURIComponent(caseId)}` : ""}`
  );

  const saveToEnterprise = async () => {
    const selectedTaric10 = clean(packageData?.taric10) || taric10;
    if (!selectedTaric10 || !window.confirm("선택한 TARIC10과 필요 서류 목록을 수출 상품 관리에 등록하시겠습니까?")) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const response = await importClassification({ jobId, taric10: selectedTaric10 });
      if (!response?.caseId) {
        throw new Error("수출 상품을 등록하지 못했습니다.");
      }
      navigate(`/enterprise?caseId=${encodeURIComponent(response.caseId)}&panel=docs`);
    } catch (saveError) {
      setError(String(saveError?.message || saveError));
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      setPackageData(null);
      try {
        const detail = await getJson(
          `/api/runs/${encodeURIComponent(jobId)}/document-packages/${encodeURIComponent(taric10)}`,
        );
        if (!cancelled) {
          setPackageData(detail.document_package || detail);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(String(loadError?.message || loadError));
        }
      }
      try {
        const collection = await getJson(
          `/api/runs/${encodeURIComponent(jobId)}/document-packages`,
        );
        if (!cancelled) {
          setPackages(asList(collection.packages));
        }
      } catch {
        /* 목록은 보조 정보 — 실패해도 상세 렌더는 유지 */
      }
      if (!cancelled) {
        setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [jobId, taric10]);

  return (
    <div className="grid min-w-0 gap-4">
      <Link className="w-fit text-sm font-semibold text-primary hover:underline" to={returnTarget}>
        ← {caseId ? "프로젝트 서류 관리" : "품목 분류"}
      </Link>
      <WorkspaceHeader
        eyebrow="EU Import Documents"
        title="TARIC 상세 서류 추천"
        description="선택한 TARIC10에 적용될 수 있는 서류와 확인 조건을 검토합니다. 최종 제출 요건은 관할기관 또는 전문가의 확인이 필요합니다."
        badge="서류 검토 워크스페이스"
        actions={(
          <div className="flex flex-wrap justify-end gap-2">
            {clean(packageData?.cn8) ? <Badge variant="secondary">CN8 {clean(packageData.cn8)}</Badge> : null}
            <Badge variant="outline">TARIC10 {clean(packageData?.taric10) || taric10}</Badge>
          {!caseId ? (
              <Button type="button" disabled={!packageData || saving} onClick={saveToEnterprise}>
              {saving ? "등록 중..." : "기업 프로젝트에 추가"}
              </Button>
          ) : null}
          </div>
        )}
      />

      {packages.length > 1 ? (
        <section className="rounded-xl border bg-surface p-3 shadow-[var(--shadow-surface)]">
          <div className="sm:hidden">
            <Select value={clean(packageData?.taric10) || taric10} onValueChange={(target) => navigate(PackagePath(target))}>
              <SelectTrigger className="w-full" aria-label="TARIC 서류 패키지 선택">
                <SelectValue placeholder="TARIC10 선택" />
              </SelectTrigger>
              <SelectContent>
                {packages.map((pkg) => {
                  const target = clean(pkg.taric10 || pkg.document_package_id);
                  return <SelectItem value={target} key={clean(pkg.document_package_id) || target}>{target}</SelectItem>;
                })}
              </SelectContent>
            </Select>
          </div>
          <Tabs className="hidden sm:block" value={clean(packageData?.taric10) || taric10} onValueChange={(target) => navigate(PackagePath(target))}>
            <TabsList className="h-auto max-w-full flex-wrap justify-start">
              {packages.map((pkg) => {
                const target = clean(pkg.taric10 || pkg.document_package_id);
                return <TabsTrigger value={target} key={clean(pkg.document_package_id) || target}>{target}</TabsTrigger>;
              })}
            </TabsList>
          </Tabs>
        </section>
      ) : null}

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>서류 패키지를 불러오지 못했습니다.</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {loading && !packageData ? (
        <div className="grid gap-3 rounded-xl border bg-surface p-6" role="status" aria-label="서류 추천 데이터를 불러오는 중">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : null}
      {!loading && !error && !packageData ? (
        <Alert><AlertTitle>표시할 서류 패키지가 없습니다.</AlertTitle></Alert>
      ) : null}
      {packageData ? <DocumentPackageDetail packageData={packageData} /> : null}
    </div>
  );
}
