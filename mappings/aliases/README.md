# Alias mappings status

공식 2026-08-24 schema의 table-scoped 상품명·식별자·명칭형 field에 대해
최소한의 한국어 alias만 등록합니다. Alias는 field 후보를 고를 뿐 concept,
unit, value domain, code meaning, operation을 승인하지 않습니다. 동일 상품군의
overlap은 span-aware longest-match로 처리하고, 서로 다른 field가 독립적으로
언급되면 ambiguity로 fail-closed합니다.
