import assert from "node:assert/strict";
import test from "node:test";
import { BuildImageEvidenceItems } from "./imageEvidenceAdapter.js";

test("이미지 계약이 없으면 production fixture를 만들지 않는다", () => {
  assert.deepEqual(BuildImageEvidenceItems({}), []);
});

test("snapshot 이미지 DTO를 UI 모델로만 변환한다", () => {
  assert.deepEqual(BuildImageEvidenceItems({
    image_evidence_items: [{
      image_id: "image-1",
      preview_url: "https://example.com/image.jpg",
      source_page_url: "https://example.com/product",
      status: "vlm-processing",
      discovered_at: "2026-07-23T10:00:00Z",
    }],
  }), [{
    id: "image-1",
    previewUrl: "https://example.com/image.jpg",
    sourceUrl: "https://example.com/product",
    status: "vlm-processing",
    discoveredAt: "2026-07-23T10:00:00Z",
    updatedAt: "",
    rejectionReason: "",
    failureReason: "",
  }]);
});
