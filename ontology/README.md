# Ontology contract

이 디렉터리는 최종 제출 Ontology의 위치와 생성 조건만 고정합니다. 현재는 공식 데이터 schema profiling 전 단계이므로 금융상품 class, property, 관계 또는 허용값을 추정한 TTL 파일을 만들지 않습니다.

최종 파일명 계약은 다음과 같습니다.

- `common.ttl`
- `bond_kr.ttl`
- `etf_kr.ttl`
- `etf_gl.ttl`
- `fund_pub.ttl`

실제 Ontology는 공식 `schema.xlsx`와 `datarows`의 typed profiling, 원본 컬럼 lineage, 결측·단위·코드값 분석, 팀 승인 mapping이 준비된 뒤 생성합니다. 생성 후에는 문법 검증, namespace 고정, shape/constraint 검사와 mapping coverage 회귀 테스트를 통과해야 합니다.

검증된 Ontology는 runtime semantic layer에서 질의 용어를 canonical concept와 source field로 grounding하고, route 및 evidence 해석을 제한하는 데 사용합니다. 원본 데이터보다 우선하는 사실 저장소나 근거 없는 상품 지식으로 사용하지 않습니다.

