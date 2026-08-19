# Data pipeline

G1 Data에서 공식 4종 금융상품 snapshot의 구조와 값 품질을 원본 보존
상태로 확인하는 작업 영역입니다. 현재 구현된 실행 단계는
[`profiling/`](profiling/README.md)의 read-only profiler뿐이며, 데이터 적재나
canonical type/schema를 추정하지 않습니다.

후속 `ingest`, `normalize`, `entity_resolution`, `indexing` 디렉터리는 계획된
경계만 나타냅니다. 각 단계를 구현할 때 입력 snapshot/version, 출력 artifact,
lineage, validation 결과를 명시해야 다음 단계로 넘어갑니다.
