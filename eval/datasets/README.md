# Evaluation datasets

`team_golden_queries_v1.json`은 공식 ground truth가 아닌 56건의 evaluation
simulation입니다. 네 상품군을 각 14건으로 구성하고 expected routing/status,
semantic key, operation, simulation result metadata, rationale와 evidence basis를
명시합니다. 기존 44건을 유지하면서 상품군별 명칭형 text capability에 대해
SUPPORTED exact EQ, NO_MATCH exact EQ, 미승인 text SORT_DESC를 각 1건씩 추가해
일반화된 성공·0행·fail-closed 경로를 균형 있게 검증합니다. Fixture 수치는 실제
staging 사실로 주장하지 않습니다.
Filter 값과 Top-N limit도 expected metadata로 보존하여 live runner가 parser와
독립적인 structured oracle contract를 재현할 수 있습니다. Simulation의 강제
zero-row fixture와 live staging 상태가 다르면 report가 expectation variation으로
분리해 기록합니다.
