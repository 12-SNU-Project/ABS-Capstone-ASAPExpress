import { useMemo } from "react";
import { asList, asObject, clean } from "../../../lib/format.js";

function ComponentDone(result, nameFragment) {
  return asList(result?.component_results).some(
    (entry) => clean(entry.component_name).toLowerCase().includes(nameFragment) && entry.success,
  );
}

function EventStatus(result, stageNames) {
  let status = "idle";
  asList(result?.events).forEach((event) => {
    if (stageNames.includes(clean(event.stage))) status = clean(event.status) || status;
  });
  return status;
}

function NormalizeStageState(status) {
  const value = clean(status).toLowerCase();
  if (["completed", "complete", "done"].includes(value)) return "done";
  if (["running", "queued", "submitting", "failed", "skipped"].includes(value)) return value;
  return "idle";
}

export function useClassificationViewModel(result) {
  return useMemo(() => {
    const candidateSet = asObject(result?.candidate_code_set);
    const candidates = asList(candidateSet.candidates);
    const packages = asList(result?.document_packages).slice();
    if (result?.document_package && typeof result.document_package === "object") {
      const packageId = clean(
        result.document_package.document_package_id || result.document_package.taric10,
      );
      if (!packages.some((item) => clean(item.document_package_id || item.taric10) === packageId)) {
        packages.push(result.document_package);
      }
    }
    const packagesByTaric = {};
    packages.forEach((item) => {
      const taric = clean(item.taric10);
      if (taric) (packagesByTaric[taric] = packagesByTaric[taric] || []).push(item);
    });
    return { candidateSet, candidates, packagesByTaric };
  }, [result]);
}

export function GetPipelineStageState(result, viewModel, key) {
  if (key === "product_collection") {
    const event = NormalizeStageState(EventStatus(result, ["Kurly_Product_Collection"]));
    if (event !== "idle") return event;
    return result?.input_processing_view || viewModel.candidates.length ? "done" : "idle";
  }
  if (key === "classification") {
    if (viewModel.candidates.length) return "done";
    const event = NormalizeStageState(EventStatus(result, [
      "Input_Intake",
      "Evidence_Intake_Component",
      "Product_Understanding_Component",
      "HS2_Routing_Component",
      "Classification",
      "Classification_Component",
    ]));
    if (event !== "idle") return event;
    return ComponentDone(result, "classification") ? "done" : "idle";
  }
  if (key === "document_recommendation") {
    const event = NormalizeStageState(EventStatus(result, ["Document_Component"]));
    if (event !== "idle") return event;
    return asList(result?.document_packages).length || result?.document_package ? "done" : "idle";
  }
  return "idle";
}
