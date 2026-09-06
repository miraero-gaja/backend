# Team Golden Query baseline — 2026-08-24

> Team evaluation benchmark only. This is not official evaluation ground truth.

- Mode: `live`
- Live staging used: `True`
- Generation: `deterministic`
- Cases: 56
- Exact case pass: 56/56 (100.0%)
- Routing accuracy: 100.0%
- Status accuracy: 100.0%
- Semantic grounding accuracy: 100.0%
- Operation accuracy: 100.0%
- Result correctness: 100.0%
- Ordering correctness: 100.0%
- Evidence validity: 100.0%
- Answer schema validity: 100.0%
- Fail-closed violations: 0
- Latency p50/p95: 61.668/208.811 ms

## Product-family pass rate

- 공모펀드: 14/14 (100.0%)
- 국내 ETF: 14/14 (100.0%)
- 국내채권: 14/14 (100.0%)
- 해외 ETF: 14/14 (100.0%)

## Result validation coverage

- EVALUATED: 31
- UNSUPPORTED_CASE_HAS_NO_RESULT_SET: 25

## Dataset/live expectation variations

- `etf-kr-01`: SUPPORTED → NO_MATCH
- `etf-kr-03`: SUPPORTED → NO_MATCH
- `etf-gl-09`: NO_MATCH → SUPPORTED
- `fund-01`: SUPPORTED → NO_MATCH
- `fund-03`: SUPPORTED → NO_MATCH
- `bond-12`: SUPPORTED → NO_MATCH
- `etf-kr-12`: SUPPORTED → NO_MATCH
- `etf-gl-12`: SUPPORTED → NO_MATCH

## Failure distribution


## Failed cases
