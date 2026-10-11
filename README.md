
# 미래에셋증권 금융상품 Agent — Backend

제10회 2026 미래에셋증권 AI Festival **금융상품 Agent (Financial Product Analyst)**를 위한 Python 3.13 · FastAPI 기반 백엔드입니다. 국내채권·국내 ETF·해외 ETF·공모펀드의 서로 다른 정형 데이터를 **검증 가능한 조건 검색·정렬·집계·교차상품군 조회**로 연결하고, 확보한 근거만 답변에 사용하도록 설계했습니다.

**구현 상태:** 공식 데이터 profiling·typed staging·PostgreSQL 적재/검증 도구, 온톨로지 TTL, 제한된 자연어 파서·Semantic Grounding·Structured Retrieval·Evidence Validation, 선택형 HyperCLOVA X transport를 구현했습니다. 단, **전체 자연어 질의 범위를 지원하거나 NCP 운영 배포를 마친 서비스는 아닙니다.** 로컬 기본 설정에서는 `DATABASE_URL`과 HCX 인증정보가 없어 검증할 수 없는 요청을 안전하게 처리합니다.

## 공식 금융상품 데이터셋

운영국이 **2026-08-24 재배포한 공식 data/schema 8개 파일(4개 상품군 × data·schema)**을 현재 기준으로 사용합니다. 아래 수치는 해당 재배포본의 검증된 **물리적 데이터 행 수**이며, 고유 상품 ID의 중복 제거 건수와 동일하다고 가정하지 않습니다.

| 상품군 | 공식 테이블 ID | 데이터 행 수 | 원본 컬럼 수 | 데이터 파일 |
| --- | --- | ---: | ---: | --- |
| 국내채권 | `PRBD01N001` | 21,882 | 58 | `prbd01n001_data.xlsx` |
| 국내 ETF | `PREF01N001` | 1,780 | 98 | `pref01n001_data.xlsx` |
| 해외 ETF | `PREF02N001` | 6,037 | 49 | `pref02n001_data.xlsx` |
| 공모펀드 | `PRFD01N001` | 23,676 | 75 | `prfd01n001_data.xlsx` |
| **전체** | **4개 테이블** | **53,375** | **280** | **data 4개 + schema 4개** |

- **데이터 시점:** 국내 데이터는 2026-08-22까지의 영업일, 해외 데이터는 한국시간 2026-08-23까지를 기준으로 배포된 스냅샷입니다. 배포일(08-24)과 개별 데이터 기준일을 혼동하지 않습니다.
- **버전 구분:** 2026-07-11 초기 배포본의 **145,393행**은 historical/archive입니다. 현재 데이터 규모·검색 결과·평가 검증의 근거로 사용하지 않습니다.
- **스키마 해석:** 280개는 각 테이블의 원본 컬럼 수를 **합산**한 값이며, 통합 테이블의 고유 필드가 280개라는 의미는 아닙니다. 상품군별로 컬럼 의미·단위·기간·코드 도메인이 달라 무조건 합치거나 비교하지 않습니다.
- **원본 보존:** 공식 데이터의 `0`과 `NULL`을 유지합니다. 수익률·총보수 등 특정 metric을 기준으로 조회·비교할 때 적용되는 0 제외 정책은 query-time 처리이며 원본을 수정하지 않습니다.
- **외부 자료:** 결측 보완용 supplementary 데이터는 출처·기준일·매칭 규칙 등을 분리 기록하고, 충돌 시 공식 데이터를 우선합니다. 외부 값을 공식 원본 셀에 덮어쓰지 않습니다.
- **데이터 접근:** 대회 제공 원본 workbook과 실제 DB 접속정보는 이 저장소에 게시하지 않습니다. 실행에 필요한 데이터는 허용된 로컬/운영 환경에서 별도로 준비해야 합니다.

데이터 물리적 규모의 코드 계약: [`pipeline/dataset_contract.py`](pipeline/dataset_contract.py) · 처리 흐름: [`pipeline/README.md`](pipeline/README.md) · 의미/연산 승인: [`ontology/README.md`](ontology/README.md).


## 현재 구현 범위

- `GET /healthz` 프로세스 liveness 및 **`GET /answer` 공식 5-string-field 응답 계약** (미정의 query parameter 허용·실패 상태의 schema 유지)
- 요청 파싱 → 상품군·의도 분석 → Ontology/Semantic Grounding → 검증된 Structured Query → Evidence Validation → 답변 생성·검증
- 단일 상품군의 **승인된 범위에 한해** EQ/NE/LT/LE/GT/GE, 다중 조건, ASC/DESC, Top-N, COUNT 및 parameterized SQL
- **서로 다른 2개 이상 상품군의 COUNT 교차질의**에 대한 상품군별 조회·결과 병합·실패 상태 구분 (상품군 간 수익률·AUM 직접 비교는 별도 의미/단위 검증 전 미지원)
- G1: 공식 4개 workbook 데이터·스키마 profiling, 무결성·해시 및 원본 불변성 확인
- G2-A: 전체 280개 원본 컬럼 typed mapping, NULL/0 및 기술적 lineage 보존
- G2-B: 4개 PostgreSQL staging table 계약, streaming loader 및 live/offline 검증
- G3: 5개 온톨로지 TTL(`common`, `bond_kr`, `etf_kr`, `etf_gl`, `fund_pub`)과 semantic registry 간 consistency 검증
- Query Coverage Audit: 원본 280개 컬럼 검토, **실효 승인 필드 52개** (필드가 승인됐더라도 모든 연산이 허용되는 것은 아님)
- `SUPPORTED`, `NO_MATCH`, `UNSUPPORTED`, `TOOL_FAILURE` 및 필요 시 `PARTIAL` 분리, evidence 기반 fail-closed 정책
- HyperCLOVA X Chat Completions v3의 **조건부 transport**, 응답 검증 및 결정론적 fallback (기본 설정은 비활성)
- Python 3.13·FastAPI·PostgreSQL psycopg·pytest, non-root Docker runtime 및 테스트/실험 도구


## 미구현·제한된 범위

- 임의의 자연어 질문을 처리하는 범용 NL2SQL 또는 전체 금융 질의 지원 (현재는 검증된 alias·의도·연산만 파싱)
- 상품 ID 매칭을 포함한 범용 entity resolution, 외부 금융·공시 API 기반 enrichment 파이프라인
- Vector/Graph 검색, 임베딩, re-ranking, GraphDB/pgvector의 실제 retrieval 통합
- 상품군 사이 **수익률·총보수·AUM 등 서로 다른 단위·기간의 수치 비교** (호환성 검증 전 닫힘)
- 세금·세후 Total Cost 등 독립적인 재무 계산 규칙
- **실제 HCX/NCP 운영 환경의 연결·성능 및 배포 완료 검증** (클라이언트 구현·테스트와 실서비스 연결 성공은 별도)
- 외부 접속 가능한 평가용 배포 및 Nginx/systemd/NCP 운영 설정

구현 여부와 데이터 사용 승인은 별개입니다. 코드가 존재해도 근거·단위·연산이 확인되지 않으면 답변을 생성하지 않습니다.


## Architecture

```text
GET /answer
    │
    ▼
QueryParser → OntologyGrounder → QueryRouter / Query Contract
    │
    ├─ 단일 상품군: 승인된 Structured SQL → PostgreSQL (설정 시)
    ├─ 교차상품군: 상품군별 COUNT → deterministic merge
    └─ Graph / Vector / Cost: 미지원 adapter
    ▼
ToolResult → Evidence Validator → SupportDecision
    ▼
HyperCLOVA X (설정 시) / Deterministic fallback
    ▼
Answer Guard → 5-string-field JSON response
```

**로컬 기본 실행:** `DATABASE_URL` 미설정 시 실제 공식 DB 조회는 수행되지 않습니다. `HCX_ENABLED=false`가 기본이며, 인증과 endpoint를 구성해야만 HCX HTTP 호출을 시도합니다. 설정 여부만으로 live 성공을 주장하지 않습니다.

정확한 숫자·필터·정렬·집계는 PostgreSQL과 결정론적 로직이 담당하며, HCX에는 검증된 Evidence만 전달합니다. 근거가 부족하면 `UNSUPPORTED`, 유효한 질의의 검색 결과가 0건이면 `NO_MATCH`, 도구/DB 장애는 `TOOL_FAILURE`로 구분합니다.

## 개발 환경

필수 환경은 Python 3.13입니다. 현재 기준 개발 버전은 Python 3.13.4입니다.

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

### macOS / Linux

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

`requirements.txt`는 Docker/운영 runtime 의존성만 포함합니다. 로컬 개발과 테스트에는 `pyproject.toml`의 `test` extra를 설치해야 합니다.

## 로컬 실행

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Swagger UI는 로컬 실행 후 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다.


## 테스트 및 재현성

```powershell
python -m pytest -q
```

테스트는 API 응답 계약, 자연어 파서와 상품군 routing, 온톨로지/semantic approval, Structured SQL compiler, evidence 검증, 실패 처리, HCX fallback 등을 대상으로 합니다.

**팀 내부 Golden Query**는 실제 대회 비공개 평가 문제의 정답이 아닙니다. 저장된 **2026-09-06 baseline 보고서** 기준으로 4개 상품군 × 14개, 총 56개 시뮬레이션 질의에서 **56/56 PASS**, 별도의 Live PostgreSQL benchmark에서도 **56/56 PASS**로 보고되었습니다. 이 수치는 해당 시점·해당 테스트셋·설정에 한정되며 현재 운영 배포 성적이나 공식 평가 정답률을 뜻하지 않습니다.

- [Simulation 보고서](eval/reports/baseline_simulation_20260906.md): deterministic fixture 기반 (DB 실행과 구분)
- [Live PostgreSQL 보고서](eval/reports/baseline_live_20260906.md): 실제 staging 기반 결과/정렬/근거 검증, deterministic generation
- [평가 방법 및 제한](eval/README.md): team golden ≠ official ground truth, 2026-07 archive 구분

```powershell
python -m eval.runners.team_golden --mode simulation
```

Live 모드는 허용된 공식 데이터가 적재된 PostgreSQL 및 유효한 `DATABASE_URL`이 있는 환경에서만 별도로 실행합니다. 실제 HCX 호출 여부도 benchmark의 generation mode와 분리해 확인합니다.

## API

### `GET /healthz`

DB나 HCX 연결 상태를 readiness로 판단하지 않고 현재 API process의 liveness만 확인합니다.

```bash
curl "http://127.0.0.1:8000/healthz"
```

```json
{
  "status": "ok"
}
```

### `GET /answer`

공식 endpoint는 인증 헤더나 request body 없이 GET query parameter만 사용합니다. 정상·unsupported·입력 누락 응답은 HTTP 200과 `application/json; charset=utf-8`을 유지합니다.

Query parameter:

| 이름 | 타입 | 계약 |
| --- | --- | --- |
| `question_id` | string | 필수, 응답에 요청값 그대로 반환 |
| `question` | string | 필수, 응답에 요청값 그대로 반환 |

```bash
curl --get "http://127.0.0.1:8000/answer" \
  --data-urlencode "question_id=q-001" \
  --data-urlencode "question=국내 ETF를 비교해 주세요."
```

응답 형태 예시 (내용은 실행 경로·연결 상태에 따라 달라집니다):

```json
{
  "question_id": "q-001",
  "question": "국내 ETF를 비교해 주세요.",
  "retrieved_context": "<검증된 조회 근거 또는 미지원 사유>",
  "think_trace": "<검색·필터·검증의 간결한 실행 요약>",
  "answer": "<확인된 답변 또는 근거 부족 안내>"
}
```

응답은 위 다섯 필드만 가지며 모든 값은 string입니다. `think_trace`는 private Chain-of-Thought가 아니라 검증·도구 선택·fallback의 실행 요약입니다. 미정의 query parameter는 무시합니다.

평가 안정성을 위해 필수 parameter가 누락되어도 `/answer`는 HTTP 200과 동일한 다섯 필드를 반환합니다. 전달된 값은 그대로 echo하고 누락 값은 빈 문자열로 두며, `answer`와 `think_trace`에 입력 누락에 따른 unsupported 처리를 명시합니다.

## 환경변수

설정 이름과 안전한 예시는 `.env.example`에 있습니다.

| 변수 | 예시/기본 방향 | 설명 |
| --- | --- | --- |
| `APP_ENV` | `development` | 실행 환경 이름 |
| `LOG_LEVEL` | `INFO` | 애플리케이션 로그 수준 |
| `ANSWER_DEADLINE_SECONDS` | `50` | 내부 실행 deadline(코드 상 60초 이하). 공식 hard timeout 300초와 별개 |
| `HCX_ENABLED` | `false` | 기본 비활성; true이고 인증·endpoint가 유효하면 HCX v3 HTTP transport 사용 |
| `HCX_API_KEY` | 빈 값 | 향후 HCX 인증 secret |
| `HCX_API_URL` | 빈 값 | HCX Chat Completions v3 HTTPS endpoint |
| `DATABASE_URL` | 빈 값 | PostgreSQL staging 조회/적재 환경의 접속 문자열 (secret) |

`HCX_API_KEY`와 인증정보가 포함된 `DATABASE_URL`은 secret입니다. 실제 값은 Git, 문서, fixture, 이미지, 로그에 넣지 말고 로컬 환경변수나 배포 환경의 secret store로 주입합니다. `.env`는 로컬 전용이며 커밋하지 않습니다. 질문 원문 전체도 기본 INFO 로그 대상이 아닙니다. Uvicorn access log는 query string에 질문 원문이 포함되므로 애플리케이션과 권장 실행 명령에서 비활성화합니다.

## Docker

Docker 이미지는 애플리케이션 코드와 런타임 의존성만 포함하며 non-root 사용자로 실행합니다.

```bash
docker build -t mirae-financial-agent-backend:skeleton .
docker run --rm -p 8000:8000 mirae-financial-agent-backend:skeleton
```

`.dockerignore`는 `.codex-context`, `.venv`, `.env*`, 테스트와 로컬 산출물을 build context에서 제외합니다. 데이터베이스, Redis, Kubernetes, Docker Compose는 이 단계에 포함하지 않습니다.


## Directory structure

```text
backend/
├─ app/                  # FastAPI, query/agent pipeline, evidence, HCX boundary
├─ pipeline/             # data contract, profiling, normalize, structured loader
├─ mappings/             # core / alias / semantic / coverage registries
├─ ontology/             # 5개 TTL + runtime consistency 계약
├─ eval/                 # 팀 Golden Query, simulation/live benchmark
├─ artifacts/            # 검증 가능한 profiling artifact
├─ outputs/              # repo에 기록된 요약·검토 보고서
├─ tests/                # unit, integration, contract, failure 등
├─ scripts/              # 반복 실행 도구
├─ deploy/               # 운영 배포 계획 (NCP stack 미구현)
├─ .env.example          # secret 없는 환경변수 예시
├─ Dockerfile
├─ pyproject.toml
└─ requirements.txt
```

원본 공식 data/schema workbook, credentials, 개인/팀 내부 비공개 자료는 문서나 Git에 포함하지 않습니다.


## 데이터 처리 단계와 다음 작업

| 단계 | 현재 저장소의 확인 가능한 범위 | 주의사항 |
| --- | --- | --- |
| G1 / profiling | 2026-08-24 공식 source 기준 row·schema·hash 검증 | 2026-07 구버전은 archive |
| G2-A / normalize | 280개 컬럼 typed rule 및 row lineage | 0/NULL·raw 값 보존 |
| G2-B / structured | 4종 staging/loader·parameterized SQL·live 검증 경로 | DB 연결은 외부 환경변수 필요 |
| G3 / semantic·ontology | runtime registry + 5개 TTL 일치 검증 | 승인하지 않은 의미·연산은 사용 금지 |
| Core QA | 제한된 parser·cross-product COUNT, 팀 Golden 검증 | 공식 35개 평가 질의의 정답률과 구분 |
| 추후 확장 | 관계 보완·필요 시 Graph/Vector, NCP/HCX production | benchmark 개선과 배포 검증 후 반영 |

정확도와 재현성을 최우선으로 유지합니다. 기술 이름의 개수보다 **공식 snapshot 일치 → 의미/단위/연산 검증 → 결정론적 조회 → Evidence 기반 답변 → 평가 API 안정성**을 중요하게 취급합니다.

