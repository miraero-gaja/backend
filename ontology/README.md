# Submission ontology contract

이 디렉터리의 Turtle 파일은 2026-07-11 source snapshot을 기준으로 현재
structured runtime이 승인한 schema와 semantic metadata만 설명합니다. 상품
145,393건을 RDF instance로 복제하지 않으며 GraphDB나 요청별 RDF reasoning을
도입하지 않습니다.

## Files

- `common.ttl`: 공통 상품 class, approval status, operation, evidence 및
  provenance vocabulary
- `bond_kr.ttl`: `PRBD01N001` 국내채권 unresolved G3 metadata
- `etf_kr.ttl`: `PREF01N001` 국내 ETF G2 core allowlist
- `etf_gl.ttl`: `PREF02N001` 해외 ETF G3 projection/ranking approval
- `fund_pub.ttl`: `PRFD01N001` 공모펀드 G2 core allowlist

모든 파일은 안정적인 프로젝트 namespace
`urn:miraeasset:financial-agent:ontology:2026:`를 공유합니다.

## Source of truth

우선순위는 다음과 같습니다.

1. `mappings/semantic/registry.py`: G3 concept, unit, value domain, operation,
   evidence provenance
2. `mappings/core/registry.py`: G2 table-scoped field allowlist
3. `mappings/aliases/registry.py`: deterministic natural-language alias
4. `ontology/*.ttl`: 위 registry를 설명하는 제출 artifact

Python registry가 runtime source of truth입니다. TTL은 runtime permission을
확장하지 않으며, drift가 발생하면 테스트가 실패합니다. Alias는 grounding
후보일 뿐 concept, unit, domain 또는 operation 승인을 의미하지 않습니다.

## Unresolved semantics

- `PREF02N001.du_last_aum`: source-native `PROJECT`와 `SORT_DESC`만 OPEN;
  통화 unit/scale 및 absolute threshold는 미승인
- `PREF02N001.cu_charge_rt`: concept만 확인; unit/scale/0 의미 및 numeric
  operation은 미승인
- `PREF02N001.pd_exg_mkt_cd`: 관측값의 의미를 부여하지 않은 unresolved
  source field
- `PRBD01N001.PD_RISK_GCD`: 0~6 의미와 위험 방향 미승인
- `PRBD01N001.DUR`, `NDY_DUR`, `COV`: 정확한 금융 의미, unit 및 상호 구분
  미승인

미확정 항목은 `UNKNOWN`, `NEED_REVIEW`, `UNMAPPED`, `closedOperation` 또는
operation 부재로 표현합니다. 확정 unit이나 code meaning을 생성하지 않습니다.

## Validation

RDF dependency가 없으므로 새 패키지 없이 제출 파일이 사용하는 보수적인
Turtle subset을 전부 tokenizing/parsing하고 QName을 확장한 triple graph를
registry와 비교합니다. 단순 문자열 존재 검사가 아닙니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/structured/test_ontology_contract.py
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

검증 범위는 필수 파일, 문법, namespace, logical table, G2/G3 semantic key와
source column, OPEN/CLOSED operation, unresolved 상태, alias, snapshot provenance를
포함합니다.
