# 미래에셋 금융상품 Agent Backend Skeleton

공식 평가 API 계약을 먼저 고정하고, 이후 Data·Ontology·Retrieval·HyperCLOVA X를 근거 기반으로 연결하기 위한 Python 3.13 / FastAPI 기반입니다.

> 이 저장소는 아직 완성된 금융상품 Agent가 아닙니다. 실제 금융상품 데이터와 HCX가 연결되지 않았으며, 현재 `/answer`는 근거 없는 상품명이나 수치를 만들지 않고 안전한 `UNSUPPORTED` 응답을 반환합니다.

## 현재 구현 범위

- 외부 의존성과 무관한 process liveness용 `GET /healthz`
- 공식 평가 계약을 따르는 `GET /answer`
- 요청값 echo, 정확히 다섯 개 문자열 필드, unknown query parameter 허용
- 필수 query parameter 누락과 미지원 질의에도 HTTP 200으로 동일 schema를 유지하는 평가 안전 정책
- Query, Tool Result, Evidence, Support Decision의 typed runtime contract
- 환경변수 기반 설정, 구조화된 운영 로그 필드, deadline 기반 실행 경계
- 비활성 HCX interface와 no-evidence fallback
- G1 4종 workbook profiling과 원본 불변성 검증
- G2-A 전체 207개 컬럼 typed rule, raw-preserving lineage와 coverage mapping
- G2-B 4개 PostgreSQL staging table 계약, streaming loader와 적재 검증
- 공식 설명으로 확인한 Priority-A 34개 필드 allowlist와 parameterized Structured Query compiler
- EQ/NE/LT/LE/GT/GE, 다중 filter, ASC/DESC, Top-N, COUNT의 결정론적 실행 계약
- 단위·통합·계약·장애 테스트를 확장할 수 있는 테스트 구조
- Python 3.13 non-root 최소 Docker runtime

## 아직 구현하지 않은 범위

- 인증된 PostgreSQL에 대한 공식 145,393행 live 적재 완료 증거
- 자연어를 검증된 Structured Query Contract로 만드는 parser/grounding
- entity resolution과 자유 NL2SQL (자유 NL2SQL은 계획하지 않음)
- 실제 금융 Ontology class/property와 TTL 산출물
- Vector/Graph 검색, embedding, re-ranking, 별도 GraphDB 또는 pgvector
- 실제 세금·Total Cost 계산 규칙
- 실제 HyperCLOVA X 또는 외부 금융 API 호출
- Nginx, systemd, NCP 등 운영 배포 설정

이 기능들은 공식 schema, snapshot, mapping 및 검증 데이터가 준비된 Gate에서만 추가합니다.

## Architecture

```text
GET /answer
    │
    ├─ Input validation + request context/deadline
    ▼
Typed QueryContract
    ▼
Parser → Grounder → Deterministic Router → Executor
                                      ├─ Structured adapter
                                      ├─ Graph adapter (placeholder)
                                      ├─ Vector adapter (placeholder)
                                      └─ Cost rules (placeholder)
    ▼
ToolResult → Evidence validation → SupportDecision
    ▼
HCX boundary (disabled) / Safe fallback → Answer guard → 5-field serializer
```

현재 공개 `/answer` 실행 경로는 자연어 structured parser와 DB connection이 주입되지 않아 `no-evidence` fallback으로 종료합니다. Structured compiler/loader는 구현되어 있지만 명시적인 typed query와 인증된 `DATABASE_URL` 없이는 실행되지 않습니다. Graph, Vector, Cost, HCX adapter는 여전히 미연결입니다.

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

## 테스트

```powershell
python -m pytest
```

전체 suite는 liveness, 공식 응답 key/type, 요청값 echo, 한글 URL encoding, unknown parameter, 필수 parameter 누락, unsupported fallback과 hallucination 방지를 검증합니다.

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

현재 skeleton 응답 예시:

```json
{
  "question_id": "q-001",
  "question": "국내 ETF를 비교해 주세요.",
  "retrieved_context": "no-evidence | backend-skeleton",
  "think_trace": "입력 검증 → 데이터 소스 미연결 확인 → Unsupported 처리",
  "answer": "현재 검증 가능한 금융상품 데이터가 연결되지 않아 답변을 확인할 수 없습니다."
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
| `ANSWER_DEADLINE_SECONDS` | `50` | `/answer` 내부 실행 deadline. 구현 목표 60초 이하 |
| `HCX_ENABLED` | `false` | HCX adapter 활성화 플래그. 현재 호출 구현 없음 |
| `HCX_API_KEY` | 빈 값 | 향후 HCX 인증 secret |
| `HCX_API_URL` | 빈 값 | 향후 HCX endpoint |
| `DATABASE_URL` | 빈 값 | 향후 데이터 source 연결 문자열 |

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
├─ app/                  # API, runtime contracts, adapter boundaries
├─ tests/                # unit / integration / contract / failure
├─ pipeline/             # planned data preparation stages; not implemented
├─ ontology/             # filename contract only; no inferred TTL
├─ mappings/             # planned concept/alias/unit/coverage artifacts
├─ eval/                 # planned datasets, runners, metrics, taxonomy
├─ deploy/               # future deployment notes; no deployment stack yet
├─ scripts/              # future repeatable operator scripts
├─ .github/              # issue and pull-request templates
├─ .env.example          # variable names and non-secret examples
├─ Dockerfile
├─ pyproject.toml
└─ requirements.txt
```

책임이 아직 없는 영역에는 실행 코드를 가장한 빈 Python module 대신 상태와 진입 조건을 설명하는 README만 둡니다.

## G1~G5 Gate

현재 skeleton은 **G1 이전 Foundation 단계**입니다. 다음 Gate는 앞 단계의 검증 결과가 준비되어야 시작합니다.

| Gate | 완료 기준 | 다음 단계 |
| --- | --- | --- |
| G1 Data | 4종 상품 typed load, coverage 측정, 원본 row 추적 가능 | Structured baseline 구축 |
| G2 Core QA | 필터·정렬·계산·Unsupported가 Gold set에서 안정 | HCX·Evidence 통합 |
| G3 Grounding | Ontology, alias, 단위 mapping 오류를 regression test로 차단 | Vector/Graph 실험 |
| G4 Retrieval | Vector/Graph가 정해진 subset에서 deterministic baseline을 실제 개선 | Selective Router 채택 |
| G5 API | 공식 contract, timeout, fallback, public endpoint 검증 통과 | Cost Lens 검증 |

Gate를 통과하기 전에 복잡한 저장소나 검색 기술을 선행 도입하지 않습니다. 제출 시점에는 source commit/tag, 데이터 snapshot, ontology, 설정 계약과 배포 이미지 버전을 함께 고정해야 합니다.
