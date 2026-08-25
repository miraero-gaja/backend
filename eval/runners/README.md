# Evaluation runner

`team_golden.py`는 각 case를 실제 `GET /answer` 한 번으로 실행합니다. 기본
simulation backend는 production compiler가 요구하는 typed row/evidence envelope를
재현합니다. Optional live mode는 `DATABASE_URL`, HCX mode는 기존 HCX 환경변수를
사용하며 credential을 report에 기록하지 않습니다.

Live result correctness는 production parser/grounder가 만든 plan을 expectation으로
재사용하지 않습니다. Dataset의 expected semantic/filter/sort/limit metadata로 별도
oracle contract를 만들고 PostgreSQL 결과의 count/source-row identity/order를 비교합니다.
Markdown report는 Windows PowerShell 표시를 위해 UTF-8 BOM으로 기록됩니다.
