# Evaluation metrics

Runner는 routing/status/semantic/operation accuracy, result correctness, Top-N
ordering, answer schema, evidence validity, fail-closed violation, HCX fallback,
latency p50/p95와 exact-case-pass rate를 계산합니다. `live_data_used`와
`benchmark_mode`를 report에 기록하여 simulation을 live 성능으로 과장하지 않습니다.
Result correctness는 simulation fixture 또는 live PostgreSQL oracle이 있는 case만
분모에 포함합니다. 제외 case와 oracle 실패는 `result_validation_summary` 및 각
case의 `result_validation.reason`에 숨김없이 기록합니다.
