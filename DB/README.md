# DB/ — 컴파일 스크립트 전용 디렉토리

컴파일(테이블 생성·원천 파싱·어휘 수확) 관련 스크립트는 전부 여기서 관리한다.
컴파일러 본체(`branch_decision_compiler.py`)는 import 경로 때문에
`src/agents/tools/`에 남고, 여기의 러너가 호출한다. 산출물은 `DB/artifacts/`.

## 구조 (스크립트=기능별 / 산출물·로그=날짜별 자동 스탬프)

```
DB/
├── run_recompile.sh        # 재컴파일 러너 (기본=트리 원천, --legacy=구방식, --dry-run)
├── sources/                # 원천 파서 (외부 파일 → artifacts/)
│   ├── nomenclature_tree_loader.py    # Nomenclature EN.xlsx → 계층 트리 JSONL
│   └── pair_rows_vocab_harvest.py     # pair_rows → including/excluding 어휘 JSON
├── uploaders/              # Supabase 적재 (설계자 직접 실행)
│   ├── load_branch_indexes.py         # branch_index 3테이블 (P2-1)
│   └── upload_bti_csv.py              # BTI 판례 CSV 적재 (범용)
└── artifacts/              # 산출물 — 날짜 스탬프 로그 + 트리/어휘 아티팩트
```

컴파일러 본체 2개는 import 경로 때문에 src/agents/tools/에 남는다:
branch_decision_compiler.py(taxonomy 조건, --tree-source 소비 포함),
cn_predicate_llm_compiler.py(llm 술어 + EnrichSubheadingLabels).

## 수정사항 원장 (2026-07-14 기준) — 스모크 후 적용 순서

### A. 컴파일 반영분 (재컴파일로 테이블에 들어감)
- 통합 값 정화 post-pass (형제 과반 공유 값 박탈)
- dash 계층 enrich-h6 + **h6 경계 앵커** (cn8 dash 그룹 'Other'가 h6 라벨을
  오염 → 190220 residual 오인·조건 전멸 버그의 수리)
- residual 판정 leaf 세그먼트 한정

### B. 런타임 코드 (구현 완료 — 다음 런 자동 반영, 게이트로 개별 복귀 가능)
| 수정 | 게이트 | 기본 |
|---|---|---|
| quant 미파싱 확정 가드 | (가드 자체 무게이트) | ON |
| residual 승격 자격(질문 존재 필수) | `ASAP_ELIMINATION_NEEDS_QUESTIONS` | ON |
| 조상 위반 상속 | `ASAP_ANCESTOR_INHERIT` | ON |
| 라우터 키워드 개념 dedup (변형 중복 과금 수리) | `ASAP_ROUTER_KEYWORD_DEDUP` | ON |
| guardrail_redirect 보너스 — A/B 판결로 **기본 OFF** (OFF 95/82/55/57 vs ON 86/73/45/48, 재첩국·꼬막장 16류 납치) | `ASAP_ROUTER_GUARDRAIL_REDIRECT=1`로만 재활성 | **OFF** |
| wrapper 의미 분리 — 도우≠stuffed(True 과신 방지) + False 거울상 가드(lane 모순 시 lexical 폴백 — 군만두 wrapper=False 오충전 −96 실측) | `ASAP_WRAPPER_SEMANTICS` | ON |
| 서열 연속 가중 2탄 — 1/rank 지지도, 3순위 이하만 자격 박탈 | `ASAP_DECISION_ORDER_WEIGHT` | **OFF** (측정 후 결정) |

### C. 트리 원천 — 적용 완료 (2026-07-14 2차 컴파일)
`--tree-source`가 러너 기본. h4/h6/h8 라벨을 트리의 명시 계층에서 조립 —
dash 헤더(suffix 10/20)가 정확한 레벨에 조상 조건으로 부착(160249
quant_gate 5코드 실증). cn_table 밖 3,027개 제외로 후보 공간 정합.
값 창 경계 수리('mea' 파편) + 비교어 스톱워드 동반.

### C-잔여. 후속 배치 (시점·방식 확정)
1. **어휘 수확 소비** (`artifacts/heading_vocab.json`) — **런타임 lexical
   층** 배선이라 컴파일이 아닌 코드 수정: staged의 형제 비교 lexical
   점수에서 including 구문 매치를 heading 지지 증거로(+), excluding
   구문 매치를 배제 증거로(−) 반영. 게이트 `ASAP_HEADING_VOCAB`(기본
   OFF)로 넣고 **이번 트리 기준선 스모크 이후 A/B로 채택 결정** —
   점수 시맨틱을 건드리므로 기준선과 동시 도입하면 귀속이 안 된다.
2. **TARIC10 (suffix의 잔여 용도)**: suffix 80/10·20 자체는 이번 컴파일에
   이미 소비됨(그룹 헤더=조상 조건). 남은 용도는 taric10_leaf 9,399개
   (code10 뒤 2자리≠00인 suffix 80 행) — cn8 확정 후 10자리 branch
   후보 제시 단계의 원천. **hs6/cn8 90% 게이트 통과 후** 같은
   _rows_from_tree 확장으로 진입(트리에 이미 depth·조상 체인 완비).

### D. 설계 대기
- **quant 연료 (표준양식 승격)**: COI % 기재율 10%가 quant 미해결의 실물
  원인. 처방 — ① 자체 표준양식(COA)에 함량 % 필수 필드 ② 미기재 시
  분류 중단 대신 "TARIC 조건부 질문"으로 사용자에게 승격(예: "meat
  content ≥80% 여부가 1602.49 분기를 결정합니다 — 함량을 입력하세요").
  구현 위치: staged가 quant_gate undecided로 멈춘 조건을
  `pending_user_questions`로 내보내는 출구 (파이프라인 DTO 확장 필요 —
  팀장 스키마 협의 사항).
- 결정 값 낱토큰 분해 → 술어 whole-phrase 정합 (03061691 'shrimp' 단독
  매치 과신 문제)
- 검증 2건: 떡볶이 부수성분 가드 미발동 / 쪽갈비 1605.30 'lobster' true
  출처 — 신 테이블 스모크 후

## 스모크 체크리스트 (사용자 실행)
```bash
env | grep ASAP_        # 오염 점검 (전부 비어야 정상)
export ASAP_COI_ROOT="$HOME/ASAP_A/test/COI(식품원재료풀이)/"   # 식품 22건 필수
# 1런: 기본값 (신 테이블 + B 전체 ON)
# 2런: ASAP_ROUTER_GUARDRAIL_REDIRECT=0  — redirect 순효과 분리
# 3런(선택): ASAP_DECISION_ORDER_WEIGHT=1 — 서열 2탄 A/B
```
