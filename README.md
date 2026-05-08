# ABS-ASAP Capstone

<p align="center">
  <img src="https://img.shields.io/badge/Phase-1%20Processed%20Food-blue" />
  <img src="https://img.shields.io/badge/Route-Korea%20to%20EU-yellow" />
  <img src="https://img.shields.io/badge/Status-In%20Progress-green" />
</p>

<p align="center">
  <b>한국 수출기업을 위한 EU 수입요건 의사결정 지원 시스템</b>
</p>

<center>

| 항목 | 내용 |
|:---|:---:|
| 문서 분류 | README 문서 |
| 문서 생성일 | 2026-05-03 |
| 최종 수정일 | 2026-05-08 |
| 최종 수정자 | 오승담 |
| 작성자 | 오승담 |

</center>

## 1. 프로젝트 개요

  EU로 수출하는 한국 기업은 품목분류, 관세, 원산지, 식품안전, 라벨링, 인증·검사 가능성, 제출서류를 여러 공식 출처에서 개별 확인해야 함.

  해당 프로세스를 자동화하기 위해 제품 정보를 구조화하고, 공식 근거를 바탕으로 후보 코드와 후보 요건을 사람이 검토할 수 있는 형태로 생성하는 시스템을 설계.

  최종 HS/CN/TARIC   분류, 관세율, 인증, 검사, TRACES/CHED, SPS, 라벨링, 제출서류 필수 여부는 세관, 관세사, 수입자, 인증기관, 관할기관 또는 검토자의 확인이 필요.

## 2. 팀원

| 이름 | 저장소 |
|:---:|---|
| 오승담 | [@seungdam](https://github.com/seungdam) |
| 김병국 | [@ByeongGukKim](https://github.com/ByeongGukKim) |
| 김승준 | [@SJ](https://github.com/rookvw) |


## 3. 공식 출처 기준

우선 공식 출처를 사용하고, 블로그·포워더·컨설팅 페이지는 비구속 배경자료로만 취급.

| 우선순위 | 출처 |
|---:|---|
| 1 | EU Combined Nomenclature, TARIC, CLASS |
| 2 | EUR-Lex / Official Journal |
| 3 | Access2Markets, ROSA |
| 4 | TRACES, DG SANTE, EU food-safety sources |
| 5 | Korea Customs Service, UNI-PASS |
| 6 | Korean food, agriculture, export authorities |
| 7 | Secondary sources as background only |

## 4. 핵심 원칙

- 제품명만으로 최종 코드를 확정하지 않는다.
- HS, HSK, CN, TARIC을 분리한다.
- 한국 수출 측 요구사항과 EU 수입 측 요구사항을 분리한다.
- 품목분류, 원산지/FTA, 관세 조치, 비관세 조치, 식품안전/SPS, 라벨링, 상업 문서를 분리한다.
- 문서는 legally required, conditional, commercial, unknown, official confirmation needed로 나눈다.
- 모든 제품별 결과에는 사람 검토 경고를 포함한다.

