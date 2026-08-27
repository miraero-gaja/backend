# Team Golden Query baseline — 2026-08-24

> Team evaluation benchmark only. This is not official evaluation ground truth.

- Mode: `live`
- Live staging used: `True`
- Generation: `deterministic`
- Cases: 44
- Exact case pass: 44/44 (100.0%)
- Routing accuracy: 100.0%
- Status accuracy: 100.0%
- Semantic grounding accuracy: 100.0%
- Operation accuracy: 100.0%
- Result correctness: 100.0%
- Ordering correctness: 100.0%
- Evidence validity: 100.0%
- Answer schema validity: 100.0%
- Fail-closed violations: 0
- Latency p50/p95: 72.106/194.102 ms

## Product-family pass rate

- 공모펀드: 11/11 (100.0%)
- 국내 ETF: 11/11 (100.0%)
- 국내채권: 11/11 (100.0%)
- 해외 ETF: 11/11 (100.0%)

## Result validation coverage

- EVALUATED: 23
- UNSUPPORTED_CASE_HAS_NO_RESULT_SET: 21

## Dataset/live expectation variations

- `etf-kr-01`: SUPPORTED → NO_MATCH
- `etf-kr-03`: SUPPORTED → NO_MATCH
- `etf-gl-09`: NO_MATCH → SUPPORTED
- `fund-01`: SUPPORTED → NO_MATCH
- `fund-03`: SUPPORTED → NO_MATCH

## Failure distribution


## Failed cases

