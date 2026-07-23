# 이미지 수집 상태 UI 연동 계약

현재 final snapshot과 SSE에는 이미지별 상태가 없으므로 Image Stack은 비활성 상태다. 내부 OCR debug artifact의 로컬 경로는 브라우저 계약으로 사용하지 않는다.

## Snapshot

`GET /api/runs/{job_id}`의 `input_processing_view.image_evidence_items`에 다음 항목을 보존해야 한다.

```json
{
  "image_id": "image-1",
  "preview_url": "https://...",
  "source_page_url": "https://...",
  "status": "discovered | queued | vlm-processing | extracted | rejected | failed",
  "discovered_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "rejection_reason": "",
  "failure_reason": ""
}
```

`image_id`는 실행 안에서 안정적이어야 하고 `preview_url`은 브라우저가 접근할 수 있어야 한다. 새로고침 복원을 위해 완료·거절·실패 항목도 snapshot에 남긴다.

화면의 발견·대기·처리·완료·거절·실패 수와 마지막 변경 시각은 이 목록에서 계산한다. 내부 OCR 임시파일 경로 또는 전체 작업량을 알 수 없는 가상 백분율은 계약에 넣지 않는다.

## SSE

기존 `pipeline_event`를 유지하고 이미지 변경 시 `partial_result.input_processing_view.image_evidence_items`에 최신 전체 목록을 보낸다. 현재 프런트의 `partial_result` 병합은 객체 단위의 얕은 병합이므로 별도 upsert 형식은 지원하지 않는다. 같은 `image_id`의 상태 시간은 단조 증가해야 한다.

SSE만 제공하면 새로고침 시 진행 상태를 복원할 수 없으므로 snapshot이 최종 기준이다.
