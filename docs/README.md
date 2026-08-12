# ASAPExpress 실행 문서

기준 브랜치: `main`  
기준 커밋: `b9d706fa5a2794ba8d7be2e6aa761aa7a427a91b`

이 문서는 환경 구성, 빌드, 실행, 운영 점검을 다룬다.

## 읽는 순서

1. [CONFIGURATION.md](./CONFIGURATION.md)에서 설정 파일과 자격 증명을 준비한다.
2. [BUILD_AND_RUN.md](./BUILD_AND_RUN.md)에 따라 설치하고 실행한다.
3. 문제가 발생하면 [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)를 확인한다.
4. 전체 구성은 [ARCHITECTURE.md](./ARCHITECTURE.md)를 확인한다.

## 필수 환경

- Git
- Conda
- Python 3.12
- Node.js 20 이상
- npm
- Supabase PostgreSQL 접속 정보
- 현재 설정에서 사용하는 LLM API 키

## 프로젝트 구조

```text
ABS-Capstone-ASAPExpress/
├── asap_app.py                 # 통합 실행 진입점
├── config/                     # 설정 예시
├── DB/                         # DB 적재·전환용 스크립트
├── docs/                       # 현재 문서
├── src/
│   ├── backend/                # Flask API와 실행 상태 관리
│   ├── bussiness_logic/        # 업무 파이프라인 모듈
│   └── db/                     # PostgreSQL 연결 관리
├── tests/                      # Python 검증 코드
├── webapp/                     # React/Vite 프런트엔드
└── environments.yml            # Conda 환경 정의
```

## 가장 짧은 실행 순서

```bash
conda env create -f environments.yml
conda activate asap_pw
python -m playwright install chromium

cp config/.appconfig.asap_app.toml .appconfig.asap_app.toml
cp config/.env.asap_app.example .env.asap_app

cd webapp
npm ci
npm run build
cd ..

python asap_app.py
```

Windows PowerShell에서는 `cp` 대신 다음 명령을 사용한다.

```powershell
Copy-Item config/.appconfig.asap_app.toml .appconfig.asap_app.toml
Copy-Item config/.env.asap_app.example .env.asap_app
```

`.env.asap_app`에 실제 DB 접속 정보와 API 키를 입력한 뒤 실행한다.

정상 실행 주소:

- Web: `http://127.0.0.1:8060`
- Health: `http://127.0.0.1:8060/api/health`

## 전달 파일

다음 파일은 삭제하지 않는다.

```text
docs/ASAP_Ontology/linkml/generated/asap_runtime.schema.json
```

이 파일은 런타임 JSON 검증에 사용한다.
