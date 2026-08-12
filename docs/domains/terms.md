# HS/CN 후보 분류 핵심 용어와 예시

| 항목 | 내용 |
|---|---|
| 문서 분류 | 용어 정리 문서 |
| 문서 생성일 | 2026-05-03 |
| 최종 수정일 | 2026-05-08 |
| 수정자 | 오승담 |

## 목차

- [0. 문서 목적](#0-문서-목적)
- [1. 코드 체계: HS, HSK, CN, TARIC](#1-코드-체계-hs-hsk-cn-taric)
- [2. 분류 근거: CN, GRI, Notes, CLASS, BTI](#2-분류-근거-cn-gri-notes-class-bti)
- [3. 1차 분류와 후속 요건의 구분](#3-1차-분류와-후속-요건의-구분)
- [4. 공통 예시: 냉동 해물파전](#4-공통-예시-냉동-해물파전)
- [5. Phase 1 후보 탐색 범위: 16~21류](#5-phase-1-후보-탐색-범위-1621류)

## 0. 문서 목적

이 문서는 1차 MVP인 `상품정보 기반 HS/CN 후보 분류`에서 반복적으로 쓰이는 핵심 용어를 정리한다. 
목표는 HS, HSK, CN, TARIC, CLASS, BTI가 어느 단계에서 쓰이는지 구분하고, 후보 코드와 최종 코드의 차이를 이해하도록 돕는 것이다.

출처: European Commission Combined Nomenclature https://taxation-customs.ec.europa.eu/customs/common-customs-tariff-cct/tariff-classification-goods/combined-nomenclature_en / CLASS https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-customs/class-classification-information-system_en

## 1. 코드 체계: HS, HSK, CN, TARIC

`HS`는 국제 공통 기반의 6자리 상품 분류 체계다. `HSK`는 한국이 HS 6자리를 바탕으로 10자리까지 세분한 한국 측 품목번호이고, `CN`은 EU가 HS 6자리를 바탕으로 8자리까지 세분한 EU 품목분류 코드다. `TARIC`은 CN을 바탕으로 EU 조치 적용을 위해 10자리까지 확장되는 통합관세 데이터베이스 및 코드 체계다.

출처: European Commission CN 설명 https://taxation-customs.ec.europa.eu/customs/common-customs-tariff-cct/tariff-classification-goods/combined-nomenclature_en / 관세청 HSK 설명 https://www.customs.go.kr/kcs/ad/tr/trTermView.do?mi=2902&termId=2170

```text
HS Chapter        2자리   예: 19
HS Heading        4자리   예: 1905
HS Subheading     6자리   예: 1905 90
CN Subheading     8자리   예: 1905 90 80
TARIC Code       10자리   예: 1905 90 80 00 또는 다른 TARIC 세분
```

| 용어 | 의미 | 활용 방식 |
|---|---|---|
| HS | WCO 기반 국제 6자리 분류 | 후보 4/6자리 도출 |
| HSK | 한국 10자리 품목분류 | 한국 수출신고 참고. EU CN 근거 아님 |
| CN | EU 8자리 품목분류 | 1차 MVP의 핵심 후보 코드 |
| TARIC | EU 조치 조회용 10자리 체계 | 후보 CN 이후 후속 조치 조회 |

1차 과제에서 “HS-Code 분류”라고 말할 때는 내부적으로 `HS 6자리 후보 + EU CN 8자리 후보 도출`을 의미한다. 최종 법적 분류나 TARIC 조치 확정이 아니다.

## 2. 분류 근거: CN, GRI, Notes, CLASS, BTI

품목분류의 기준 원천은 CLASS가 아니라 CN 법령 구조와 해석 규칙이다. CN에는 preliminary provisions, goods descriptions, section/chapter notes, additional notes, duty rates, supplementary units가 포함된다.

출처: European Commission CN 설명 https://taxation-customs.ec.europa.eu/customs/common-customs-tariff-cct/tariff-classification-goods/combined-nomenclature_en

`GRI`는 General Rules for Interpretation의 약어다. 복합식품은 제품명만으로 분류하지 않고 상품의 객관적 특성, 성분, 함량, 공정, 형태, 용도, 관련 notes를 함께 검토해야 한다.

`CLASS`는 여러 classification information에 접근하는 single access point다. CLASS는 Customs Code Committee conclusions, Classification Regulations, CJEU rulings, CN and CN Explanatory Notes, TARIC information을 제공한다. 따라서 CLASS는 후보 보강 근거를 찾는 포털이지, 우리 제품의 최종 코드 정답표가 아니다.

출처: CLASS official page https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-customs/class-classification-information-system_en

`BTI`는 특정 물품에 대한 tariff classification legal decision이다. 공개 BTI 또는 유사 BTI는 참고 근거가 될 수 있지만, 성분·공정·포장·용도가 다른 제품에 자동 적용하면 안 된다.

| 근거 | 증거 성격 | 사용 방식 |
|---|---|---|
| CN 법령, GRI, Section/Chapter Notes | 1차 기준 | 후보 HS/CN 판단의 중심 |
| CN description | 후보 검색 근거 | 로컬 catalog matching과 후보 생성 |
| Additional Notes | EU 세부 판단 근거 | CN 8자리 후보 검토 |
| CN Explanatory Notes | 보조 해석 근거 | heading/subheading 범위 이해 |
| Classification Regulation | 강한 공식 근거 | 유사 물품 분류 근거 |
| CJEU ruling | 강한 해석 근거 | 쟁점 있는 해석 보조 |
| BTI | 제품별 참고 근거 | 동일하지 않은 제품에는 자동 적용 금지 |
| CLASS | 근거 탐색 포털 | evidence discovery |

## 3. 1차 분류와 후속 요건의 구분

HS/CN 후보 분류와 수입요건 판단은 분리한다.

| 구분 | 질문 | 사용하는 자료 |
|---|---|---|
| 1차 분류 | 이 상품이 어느 HS/CN 후보에 들어갈 수 있는가? | CN, EUR-Lex, CN catalog, CLASS |
| 후속 TARIC | 후보 CN에 어떤 관세·조치·document code가 붙는가? | TARIC |
| 후속 수입요건 | EU 수입 절차, 원산지, 제품요건은 무엇인가? | Access2Markets, EUR-Lex |
| 후속 SPS/공식문서 | CHED, TRACES, BCP, official certificate 가능성이 있는가? | TRACES, DG SANTE, EUR-Lex |

따라서 1차 분류 문서에서 TRACES/CHED 또는 제출서류를 언급하더라도, 이를 필수 결론으로 쓰지 않는다.

## 4. 공통 예시: 냉동 해물파전

예시 제품은 `냉동 해물파전`이다. 가정 성분은 밀가루 반죽, 쪽파, 오징어, 새우, 계란, 식용유, 소금, 조미료이며, 소매포장 냉동식품으로 소비자가 가열 후 섭취한다고 본다.

이 제품은 곡물·밀가루 조제품, 해산물 조제품, 기타 식품조제품의 경계에 걸릴 수 있다. 따라서 제품명만으로 최종 코드를 정하면 안 된다. 아래 후보는 heading 수준의 초기 후보이며, 실제 1차 산출물에서는 상품정보를 보강해 HS 6자리와 CN 8자리 후보로 좁힌다.

| 후보 | 후보 사유 | 배제 또는 불확정 사유 |
|---|---|---|
| HS heading 1605 | 새우·오징어 등 수산물 조제품 성격 가능 | 해산물 함량과 본질적 성격이 불명확 |
| HS heading 1901 | 밀가루·전분 기반 조제품 성격 가능 | 조리된 식품이면 1905 또는 다른 heading 가능 |
| HS heading 1905 | 밀가루 기반 조리식품 또는 베이커리류 성격 가능 | 수산물 조제품 또는 2106 성격이 강하면 부적합 가능 |
| HS heading 2106 | 다른 heading에 명확히 들어가지 않는 기타 식품조제품 가능 | 보충적 후보이므로 16류·19류 검토 후 판단 |

후보를 좁히기 위해 필요한 질문:

| 질문 | 필요한 정보 | 연결되는 후보 |
|---|---|---|
| 해산물 성분이 본질적 성격을 주는가? | 새우·오징어 종류, 총함량, 조리상태 | 1605 |
| 밀가루 반죽이 본질적 성격을 주는가? | 밀가루·전분 비중, 배합비 | 1901/1905 |
| 제품은 완전히 조리되었는가? | 열처리 정도, 소비자 조리법 | 1905 또는 기타 후보 |
| 다른 heading에 명확히 들어가는가? | 16류/19류 포함·배제 근거 | 2106 보충 검토 |
| 소매포장인가 벌크인가? | 포장 단위, 순중량 | 일부 CN 세분 |

안전한 분석 흐름은 `상품정보 보강 -> HS/CN 후보 생성 -> CN/GRI/Notes 검토 -> CLASS 근거 수집 -> 후보 비교표 작성 -> 사람 검토`다.

## 5. Phase 1 후보 탐색 범위: 16~21류

Phase 1의 초기 후보 탐색 범위는 HS/CN 16~21류다. 이는 가공식품 MVP 후보 검색 범위이지 모든 가공식품을 포함한다는 뜻이 아니다.

| Chapter | 후보 탐색 범위 | 주의점 |
|---:|---|---|
| 16 | 육류·어류·갑각류·연체동물 등 조제품 | 동물성 원료 함량·가공상태 필요 |
| 17 | 당류와 설탕과자 | 당 함량, 코코아 함유 여부 필요 |
| 18 | 코코아와 그 조제품 | 코코아 함량, 형태, 포장 필요 |
| 19 | 곡물·분·전분·밀크 조제품과 베이커리 제품 | 밀가루·전분·유성분·조리상태 필요 |
| 20 | 채소·과실·견과류 조제품 | 보존방식, 당·알코올, 포장 필요 |
| 21 | 각종 식용 조제품 | 다른 heading 배제 후 검토해야 하는 경우 많음 |

식용유는 15류, 유제품은 04류, 커피·차 원물은 09류, 음료는 22류가 될 수 있으므로, 시스템은 16~21류 밖 후보를 `out_of_initial_scope_candidate`로 표시할 수 있어야 한다.
