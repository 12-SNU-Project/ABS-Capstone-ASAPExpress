import { asList, asObject, clean } from "../../../lib/format.js";

const IMAGE_STATUSES = new Set([
  "discovered",
  "queued",
  "vlm-processing",
  "extracted",
  "rejected",
  "failed",
]);

export function BuildImageEvidenceItems(inputProcessingView) {
  return asList(asObject(inputProcessingView).image_evidence_items)
    .map((value) => {
      const item = asObject(value);
      const status = clean(item.status);
      return {
        id: clean(item.image_id || item.id),
        previewUrl: clean(item.preview_url || item.thumbnail_url),
        sourceUrl: clean(item.source_url || item.source_page_url),
        status,
        discoveredAt: clean(item.discovered_at),
        updatedAt: clean(item.updated_at),
        rejectionReason: clean(item.rejection_reason),
        failureReason: clean(item.failure_reason),
      };
    })
    .filter((item) => item.id && item.previewUrl && IMAGE_STATUSES.has(item.status));
}
