# Team evaluation simulation

이 디렉터리는 공식 평가 정답이 아닌 `team golden queries`를 관리합니다.
2026-07-11 승인 registry로 검증 가능한 single-turn 질의만 포함하며, 미확정
unit/code/domain 의미는 `UNSUPPORTED` competency로 보존합니다.

기본 실행은 deterministic fixture와 deterministic generation을 사용해 parsing,
grounding, retrieval contract, evidence, `/answer` schema를 재현합니다. `--mode live`
및 `--hcx`는 각각 PostgreSQL과 HCX credential이 있는 경우에만 opt-in합니다.
Live mode는 dataset metadata로 만든 별도 structured oracle query와 실제 `/answer`
결과를 source-row identity/count/order 단위로 비교하며, oracle을 만들 수 없는 case는
검증 불가 사유를 report에 명시합니다. Report 이름에는 mode가 포함됩니다.

```powershell
.\.venv\Scripts\python.exe -m eval.runners.team_golden --mode simulation
```
