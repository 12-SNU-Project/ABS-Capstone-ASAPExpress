# 화장품 도메인 문서 인덱스

| 항목 | 내용 |
|---|---|
| 문서 분류 | 인덱스 문서 |
| 문서 생성일 | 2026-05-08 |
| 최종 수정일 | 2026-05-08 |
| 수정자 | 오승담 |

## 0. 결론

이 폴더는 화장품 도메인 자료를 식품 문서와 분리해 관리한다. 공통 상품 탐색, HS/CN 후보 구조, evidence package는 `docs/architecture`를 따른다.

화장품 문서에서는 TRACES/CHED, Novel Food, 식품첨가물, 식품 알레르겐 규칙을 적용하지 않는다.

## 1. 현재 문서 범위

이 도메인 폴더는 현재 인덱스만 유지한다. 기존 CN Chapter 33 tree는 원자료와 생성 절차가 코드와 연결되지 않았고, 공식 수집 pipeline이 아직 없으므로 제거했다.

## 2. 3주차 수집 대상

| 영역 | 공식 출처 후보 |
|---|---|
| 화장품 기본 규정 | Regulation (EC) No 1223/2009 |
| notification | CPNP |
| ingredient reference | CosIng |
| safety opinion | SCCS opinions |
| compliance package | Responsible Person, PIF, CPSR, GMP evidence |

## 3. 사람 검토 경고

화장품 도메인 산출물은 후보 검토 자료다. CPNP, Responsible Person, PIF, CPSR, ingredient restriction, claims, labelling, 최종 HS/CN/TARIC 분류는 검토자가 공식 근거와 제품 사실관계를 확인해야 한다.
