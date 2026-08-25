# Archived: 2026-07-11 Team Golden (historical)

이 디렉터리는 `eval/datasets/team_golden_queries_v1.json`이
`source_snapshot: "2026-07-11"` 기준으로 사용하던 시점의 dataset과, 그 시점에
로컬에서 실행한 simulation report를 그대로 보존한 historical artifact입니다.

- `team_golden_queries_v1.json`: 2026-07-11 기준 40 case 원본 dataset. 당시
  `mappings/aliases/registry.py`가 "듀레이션"/"duration" alias를 dur, ndy_dur,
  cov 세 필드 모두에 중복 등록했던 상태를 전제로 `bond-04`/`bond-05`가
  `AMBIGUOUS_FIELD`(3-way ambiguity)로 작성되어 있습니다.
- `baseline_simulation_20260825.json` / `.md`: 위 dataset을 2026-08-25에
  로컬에서 실행한 simulation report (`passed: 40, evaluated: 40, rate: 1.0`).

## 이 dataset이 더 이상 current가 아닌 이유

`feat/official-data-0824-migration` 브랜치에서 semantic registry, ontology,
alias registry가 2026-08-24 공식 schema/evidence 기준으로 migration되면서:

- PRBD01N001의 `pd_risk_gcd`/`dur`/`ndy_dur`/`cov` concept이 T1_OFFICIAL_SCHEMA
  CONFIRMED로 바뀌었고,
- alias resolution이 span-aware longest-match로 바뀌어 "듀레이션"/"익일
  듀레이션"/"컨벡시티"가 각각 정확히 하나의 필드로만 resolve됩니다.

그 결과 이 dataset의 `bond-04`/`bond-05` 기대값(3-way ambiguity)은 현재
runtime과 더 이상 일치하지 않습니다. Current dataset은
`eval/datasets/team_golden_queries_v1.json`(`source_snapshot: "2026-08-24"`)을
참조하세요.

이 디렉터리의 파일은 재실행 대상이 아니며, 과거 상태를 추적하기 위한 기록
목적으로만 보존합니다.
