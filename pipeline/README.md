# Data pipeline (planned)

G1 Data에서 공식 4종 금융상품 snapshot을 원본 보존 상태로 typed load하기 위한 작업 영역입니다. 현재 실행 pipeline은 없으며 schema나 저장소를 추정하지 않습니다.

단계 순서는 `ingest → profiling → normalize → entity_resolution → indexing`입니다. 각 단계는 입력 snapshot/version, 출력 artifact, row-level lineage, validation 결과를 명시해야 다음 단계로 넘어갑니다.

