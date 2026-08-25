# Team evaluation simulation

이 디렉터리는 **공식 평가 정답(official Ground Truth)이 아닌** `team golden
queries`를 관리합니다. 아래 5가지는 이 디렉터리를 사용하는 누구나 오해하지
않도록 명시적으로 유지해야 하는 전제입니다.

- **Team Golden != official Ground Truth.** `eval/datasets/*.json`은
  `"official_ground_truth": false`를 명시적으로 요구하며(`load_dataset`이 이를
  강제합니다), 팀이 현재 runtime 동작을 회귀 검증하기 위해 구축한 참고
  benchmark일 뿐입니다. 공식 평가 정답이 별도로 존재한다면 그쪽이 우선합니다.
- **Current snapshot = 2026-08-24.** `eval/datasets/team_golden_queries_v1.json`은
  현재 `mappings/semantic/registry.py`, `mappings/aliases/registry.py`,
  `ontology/*.ttl`이 채택하고 있는 2026-08-24 공식 schema/evidence 기준
  registry로 검증 가능한 single-turn 질의만 포함합니다. 미확정 unit/code/domain
  의미는 여전히 `UNSUPPORTED` competency로 보존합니다.
- **20260711은 historical only.** 이전 2026-07-11 기준 dataset과 그 시점의
  simulation report는 `eval/archive/20260711/`에 그대로 보존되어 있습니다.
  그 디렉터리의 파일은 재실행 대상이 아니며, 과거 상태를 추적하기 위한 기록
  목적으로만 존재합니다. 자세한 내용은 `eval/archive/20260711/README.md`를
  참고하세요.
- **simulation != live PostgreSQL benchmark.** 기본 실행(`--mode simulation`)은
  deterministic fixture와 deterministic generation을 사용해 parsing, grounding,
  retrieval contract, evidence, `/answer` schema를 재현합니다. 실제 DB row/결과
  개수가 필요한 case(`expected_status`가 `SUPPORTED`/`NO_MATCH`인 case)는
  simulation 모드에서 고정된 fixture 값으로만 평가되며, 실제 PostgreSQL 데이터에
  대한 검증이 아닙니다. `--mode live`는 `DATABASE_URL`이 있는 경우에만 opt-in하며,
  dataset metadata로 만든 별도 structured oracle query와 실제 `/answer` 결과를
  source-row identity/count/order 단위로 비교합니다. `--hcx`는 HCX credential이
  있는 경우에만 opt-in합니다. oracle을 만들 수 없는 case는 검증 불가 사유를
  report에 명시합니다. Report 이름에는 mode가 포함됩니다.
- **old PASS는 current PASS의 근거가 아닙니다.** `eval/archive/20260711/`에
  보존된 "40/40 PASS" 결과는 그 시점의 registry/alias 상태(예: "듀레이션"
  alias가 dur/ndy_dur/cov 세 필드 모두에 중복 매핑되어 있던 상태)를 전제로
  성립했던 결과이며, registry가 migration된 지금은 그 dataset의 일부 기대값이
  더 이상 현재 runtime과 일치하지 않습니다(`bond-04`/`bond-05`가 대표적
  사례). 현재 registry/alias/ontology에 대한 PASS 여부는 항상
  `eval/datasets/team_golden_queries_v1.json`(현재 snapshot)을 현재 코드로
  재실행해서만 판단해야 하며, 과거 report를 근거로 재사용해서는 안 됩니다.

```powershell
.\.venv\Scripts\python.exe -m eval.runners.team_golden --mode simulation
```
