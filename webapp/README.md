# ASAP Webapp (React)

ASAP 프론트엔드. 분류 워크벤치(`/classification`), 관리자 Run Inspector(`/admin`),
TARIC 서류 추천(`/document/:jobId/:taric10` — 팀원 렌더러를 alias로 참조)을 제공한다.

## 실행

```bash
# 평소: 백엔드 하나로 UI+API 전부 (:8060, webapp/dist 서빙)
python asap_app.py

# 프론트 코드 수정 후: 빌드 한 번 (백엔드 재시작 불필요, 새로고침만)
cd webapp && npm run build

# 프론트 활발히 개발 중일 때만: 핫리로드 dev 서버 (:5173)
cd webapp && npm run dev
```

dev 모드의 `/api/*` 요청은 Vite 프록시가 `http://127.0.0.1:8060`으로 전달하므로 CORS 설정이 필요 없다.
백엔드 주소가 다르면 `VITE_API_PROXY_TARGET`으로 지정한다.

## 환경 변수

| 변수 | 기본값 | 용도 |
| --- | --- | --- |
| `VITE_API_PROXY_TARGET` | `http://127.0.0.1:8060` | dev 프록시 대상 |
| `VITE_API_BASE_URL` | `""` (same-origin/proxy) | 빌드 산출물이 API와 다른 origin에서 서빙될 때 절대 주소 |

## 빌드

```bash
npm run build   # dist/ 생성 → asap_app.py가 자동 서빙
```

`dist/`를 별도 origin에서 서빙하면 `../config/.appconfig.asap_app.toml`의
`allowed_frontend_origins`에 해당 origin을 추가해야 한다.

## 구조

- `src/hooks/useClassificationRun.js` — run 생성/SSE 스트림/스냅샷 hydrate/세션 복원(jobId sessionStorage)
- `src/pages/WorkbenchPage.jsx` — 분류 워크벤치 (현행 `product_understanding_view`/`routing_view` 필드명 기준)
- `src/pages/AdminPage.jsx` — 관리자 Run Inspector (`/api/admin/runs/<job_id>/blackboard`)
- `src/pages/DocumentPage.jsx` — TARIC 서류 추천 (`@docreco` alias = `src/frontend/ui/assets/demo/document_recommendation` 원본 참조)
- `src/lib/labels.js` — 현행 DTO 필드명 ↔ 한글 라벨 매핑 (단일 소스)
- `src/styles/workbench.css`, `admin.css` — 기존 CSS를 클래스명 그대로 재사용
