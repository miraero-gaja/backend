# G1 Data Profiling Summary

- Data profiling status: **PASS**
- Expected total rows: 53,375
- Observed total rows: 53,375
- Source immutable check: PASS
- Scope: schema/data truth only; canonical schema, finance meaning, units, and keys are not inferred.

## File inventory

| Kind | Logical table | Physical filename | SHA-256 | Sheets |
|---|---|---|---|---|
| datarows | PRBD01N001 | PRBD01N001_국내채권마스터_20260824_datarows.xlsx | `574ae5d6c1d98704712c256ed5352cbaed065ea9c3a6eb7b2a52adb305fa9001` | data |
| schema | PRBD01N001 | PRBD01N001_국내채권마스터_schema.xlsx | `9965126695066f9dc07951a78054e9e7639b6863d1ad2a9616f7e2d8fcadbc4f` | schema |
| datarows | PREF01N001 | PREF01N001_국내ETF마스터_20260824_datarows.xlsx | `18c4329d8fc8768d030316816f3e6e48226a3c217db3354245b766a2c6f6c592` | data |
| schema | PREF01N001 | PREF01N001_국내ETF마스터_schema.xlsx | `2135081fd8107760d127915147032987ee1d9e7c2ed039665ae4214b96faec5a` | schema |
| datarows | PREF02N001 | PREF02N001_해외ETF마스터_20260824_datarows.xlsx | `ca6a274aeaf3f884f2f7635d7802558bc6dabf408871ecb1f71e5a50d9d34067` | data |
| schema | PREF02N001 | PREF02N001_해외ETF마스터_schema.xlsx | `32ac732f0501f4ab518682175fecc50756ee1eafde9296801f139d62559b5e64` | schema |
| datarows | PRFD01N001 | PRFD01N001_공모펀드마스터_20260824_datarows.xlsx | `81b3ce3f1d5042b32fd52a76acff094fc5b8dd9fa36289af2fb54c195eb5d94c` | data |
| schema | PRFD01N001 | PRFD01N001_공모펀드마스터_schema.xlsx | `cfe7be44cbcd9ce349206776a4eb46996162643acbf3ca5a4f74c2886394862b` | schema |

## Row and column verification

| Logical table | Expected rows | Observed rows | Row status | Schema columns | Data columns | Column status |
|---|---:|---:|---|---:|---:|---|
| PRBD01N001 | 21,882 | 21,882 | MATCH | 58 | 58 | MATCH |
| PREF01N001 | 1,780 | 1,780 | MATCH | 98 | 98 | MATCH |
| PREF02N001 | 6,037 | 6,037 | MATCH | 49 | 49 | MATCH |
| PRFD01N001 | 23,676 | 23,676 | MATCH | 75 | 75 | MATCH |

## Schema differences

### PRBD01N001

- Schema only: 없음
- Data only: 없음
- Exact order match: True

### PREF01N001

- Schema only: 없음
- Data only: 없음
- Exact order match: True

### PREF02N001

- Schema only: 없음
- Data only: 없음
- Exact order match: True

### PRFD01N001

- Schema only: 없음
- Data only: 없음
- Exact order match: True

## Identifier evidence

### PRBD01N001

- Schema-declared key status: NOT_DECLARED_IN_SCHEMA
- Schema-declared columns: 없음
- Statistical candidates: 없음
- Candidate means observed unique and nonblank only; it is not a confirmed primary key.

### PREF01N001

- Schema-declared key status: NOT_DECLARED_IN_SCHEMA
- Schema-declared columns: 없음
- Statistical candidates: pd_itm_no#1, pd_itm_no_ma#1, pd_nm#1
- Candidate means observed unique and nonblank only; it is not a confirmed primary key.

### PREF02N001

- Schema-declared key status: NOT_DECLARED_IN_SCHEMA
- Schema-declared columns: 없음
- Statistical candidates: pd_itm_no#1, pd_itm_no_ma#1
- Candidate means observed unique and nonblank only; it is not a confirmed primary key.

### PRFD01N001

- Schema-declared key status: NOT_DECLARED_IN_SCHEMA
- Schema-declared columns: 없음
- Statistical candidates: itm_no#1
- Candidate means observed unique and nonblank only; it is not a confirmed primary key.

## Major quality evidence

### PRBD01N001

- Columns with observed null/blank: 35
- Highest null/blank columns (max 10): after_tax_yield#1, avg_annual_tax_yield#1, bdbns_abl_chnl_nm#1, bdbns_abl_chnl_tcd#1, buyable_quantity#1, buy_yield#1, corp_after_tax_yield#1, corp_pretax_yield#1, depo_equiv_yield_154#1, depo_equiv_yield_495#1
- Columns with leading/trailing whitespace: 7
- Columns with mixed observed types: 18
- Excel error cells: 0
- Explicit schema unit declarations: 0

### PREF01N001

- Columns with observed null/blank: 83
- Highest null/blank columns (max 10): fn_average_maturity#1, fn_effective_duration#1, fn_modified_duration#1, pd_dvid_inc_dist#1, cu_base_index#1, fn_average_quality#1, fn_average_coupon#1, fn_effective_maturity#1, fn_nominal_maturity#1, cu_charge_etc_rt#1
- Columns with leading/trailing whitespace: 5
- Columns with mixed observed types: 23
- Excel error cells: 0
- Explicit schema unit declarations: 0

### PREF02N001

- Columns with observed null/blank: 34
- Highest null/blank columns (max 10): du_diff_rt#1, cu_etn_yn#1, wu_core_yn#1, cu_inverse_short_yn#1, du_last_nav#1, cu_lev_fector#1, cu_index_repl_mthd#1, cu_index_tracking_yn#1, du_last_aum#1, pd_us_cik#1
- Columns with leading/trailing whitespace: 0
- Columns with mixed observed types: 11
- Excel error cells: 0
- Explicit schema unit declarations: 0

### PRFD01N001

- Columns with observed null/blank: 48
- Highest null/blank columns (max 10): fd_wk1_ern_r#1, itm_eabrv_nm#1, fd_yr5_ern_r#1, han_clas_policies#1, fd_yr3_ern_r#1, fd_yr2_ern_r#1, fd_mm18_ern_r#1, exchdg_yn#1, fd_yr1_ern_r#1, fd_mm6_ern_r#1
- Columns with leading/trailing whitespace: 13
- Columns with mixed observed types: 22
- Excel error cells: 0
- Explicit schema unit declarations: 0

## Interpretation guardrails

- Numeric-like, date-like, code-like, enum, and identifier results are evidence-based candidates only.
- An eight-digit valid calendar value is a lexical/value-shape date candidate, not a confirmed date datatype.
- A numeric magnitude is never reinterpreted as a percentage, currency, or unit.
- Distinct counts use typed SHA-256 digests in an ephemeral SQLite store; source rows and arbitrary value samples are not written to reports.
- Requested bounded evidence such as numeric/date extrema, numeric-like-string extrema, boolean-code representations, and low-cardinality code counts is included when observed.
- Bounded code counts preserve source tokens and frequencies only; code meanings are never inferred.
- Schema example values are intentionally omitted from generated reports.
