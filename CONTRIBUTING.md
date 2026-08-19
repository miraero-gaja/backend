# Contributing

이 저장소는 공식 평가 계약을 먼저 고정하고 데이터·검색·LLM 기능을 단계적으로 연결합니다. 변경량보다 재현성, 근거 추적성, 안전한 실패를 우선합니다.

## 개발 환경

- Python 3.13을 사용합니다.
- 저장소 루트의 `.venv`를 권장하며 Git에 추가하지 않습니다.
- 의존성은 `requirements.txt`와 `pyproject.toml`에 일치하게 유지합니다.
- 실제로 import하지 않는 런타임 의존성은 추가하지 않습니다.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m pytest
```

`requirements.txt`는 Docker/운영 runtime 전용이며 테스트 도구는 `pyproject.toml`의 `test` extra로 분리합니다.

## 변경 원칙

1. `GET /answer`의 다섯 응답 필드, 문자열 타입, 요청값 echo, HTTP 200 fallback 계약을 깨지 않습니다.
2. `think_trace`에는 실행 단계 요약만 기록하고 내부 추론이나 프롬프트를 노출하지 않습니다.
3. 공식 schema profiling 전에는 금융 컬럼, Ontology class/property, 계산식을 추정하지 않습니다.
4. 정형 실행, 의미 검색, Graph, 비용 규칙, HCX는 교체 가능한 경계로 유지합니다.
5. evidence가 없는 상품명·수치·추천을 생성하지 않습니다.
6. 질문 원문, API key, 인증 헤더, 연결 문자열을 일반 INFO 로그에 남기지 않습니다.

## 설정과 Secret

`.env.example`에는 변수 이름과 안전한 기본값만 둡니다. `.env`와 실제 key·password는 커밋하지 말고 로컬 환경변수 또는 배포 환경의 secret store로 주입합니다. 로그, fixture, 문서, 스크린샷에도 실제 secret을 넣지 않습니다.

## 테스트

변경 범위에 맞는 가장 작은 테스트부터 추가하고 전체 suite를 실행합니다.

```powershell
python -m pytest
```

API 변경에는 최소한 정상 요청, 한글 query encoding, 미정의 query parameter, 필수 parameter 누락, unsupported fallback, 정확한 응답 key/type 검증이 포함되어야 합니다. 외부 adapter가 추가되면 timeout, 비활성화, 잘못된 응답, 부분 장애도 failure test로 고정합니다.

## Pull request

- 하나의 PR은 하나의 문제를 해결하도록 작게 유지합니다.
- 동작 변경에는 테스트와 관련 문서를 함께 갱신합니다.
- PR 본문에 범위, 검증 명령과 결과, 의도적으로 제외한 작업, 설정 변경을 기록합니다.
- 사용자 데이터와 참가자 공유자료를 fixture로 복사하지 않습니다.
- merge 전 `git diff`, 전체 테스트, secret scan, 추적 파일 목록을 확인합니다.

리뷰에서는 공식 계약, 데이터 근거, 장애 시 fallback, 시간 제한, 설정 분리 순으로 확인합니다.
