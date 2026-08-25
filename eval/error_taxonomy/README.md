# Error taxonomy

`taxonomy.py`는 parsing, product scope, semantic grounding, operation, unsupported
오판, no-match, result/order, evidence, generation fallback, tool failure를 서로
분리합니다. 한 case가 여러 failure type을 가질 수 있어 근본 원인과 downstream
영향을 함께 집계합니다.
