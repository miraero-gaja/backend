# G1 Data Profiling Summary

- Data profiling status: **PASS**
- Expected total rows: 145,393
- Observed total rows: 145,393
- Source immutable check: PASS
- Scope: schema/data truth only; canonical schema, finance meaning, units, and keys are not inferred.

## File inventory

| Kind | Logical table | Physical filename | SHA-256 | Sheets |
|---|---|---|---|---|
| datarows | PRBD01N001 | PRBD01N001_국내채권마스터_20260711_datarows.xlsx | `728f44a567a986d21cf843d711c6c4dfa1a24d05b39c7da0541b981b57ecccf8` | datarows |
| schema | PRBD01N001 | PRBD01N001_국내채권마스터_schema.xlsx | `f0647ce274f94e0474960b98832b98d87838d812b4772f15bdeda2dceff3676b` | Sheet1_Schema, Sheet2_Sample |
| datarows | PREF01N001 | PREF01N001_국내ETF마스터_20260711_datarows.xlsx | `0f5706d45f93284bcaac2fa8eaed04db920a7043abaa859e455f06e246d54723` | datarows |
| schema | PREF01N001 | PREF01N001_국내ETF마스터_schema.xlsx | `17ae6befa4f0f5b60481882ff24de1f7729386cef9d9b56f32187e41f1cb00e6` | Sheet1_Schema, Sheet2_Sample |
| datarows | PREF02N001 | PREF02N001_해외ETF마스터_20260711_datarows.xlsx | `3cec19043f742771e0016d56fe806f19ad78f4295d1ae59192740a78feb2253b` | datarows |
| schema | PREF02N001 | PREF02N001_해외ETF마스터_schema.xlsx | `c6a022dd8a349363c405e7bf47b44f8cc099a92bfafb276b985a5c89d1881162` | Sheet1_Schema, Sheet2_Sample |
| datarows | PRFD01N001 | PRFD01N001_공모펀드마스터_20260711_datarows.xlsx | `140d1ef0cec918d0b3f7c52c107cb123395594eb089b0cd70bb305709b0f44eb` | datarows |
| schema | PRFD01N001 | PRFD01N001_공모펀드마스터_schema.xlsx | `eedb7e517312234b2825a6752adb2b5f11053f0f4fb93b70e83e87b56ee134e9` | Sheet1_Schema, Sheet2_Sample |

## Row and column verification

| Logical table | Expected rows | Observed rows | Row status | Schema columns | Data columns | Column status |
|---|---:|---:|---|---:|---:|---|
| PRBD01N001 | 42,394 | 42,394 | MATCH | 40 | 40 | MATCH |
| PREF01N001 | 1,734 | 1,734 | MATCH | 73 | 73 | MATCH |
| PREF02N001 | 5,646 | 5,646 | MATCH | 49 | 49 | MATCH |
| PRFD01N001 | 95,619 | 95,619 | MATCH | 45 | 45 | MATCH |

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
- Statistical candidates: PD_NO#1
- Candidate means observed unique and nonblank only; it is not a confirmed primary key.

### PREF01N001

- Schema-declared key status: SCHEMA_DECLARED
- Schema-declared columns: pd_exg_mkt_cd#1, pd_itm_no#1, pd_itm_no_ma#1
- Statistical candidates: pd_itm_no#1, pd_itm_no_ma#1, pd_nm#1
- Candidate means observed unique and nonblank only; it is not a confirmed primary key.

### PREF02N001

- Schema-declared key status: SCHEMA_DECLARED
- Schema-declared columns: pd_itm_no#1
- Statistical candidates: pd_itm_no#1, pd_itm_no_ma#1
- Candidate means observed unique and nonblank only; it is not a confirmed primary key.

### PRFD01N001

- Schema-declared key status: SCHEMA_DECLARED
- Schema-declared columns: itm_no#1, prfd_attr_cd#1, zrin_fd_ivst_risk_gcd#1
- Statistical candidates: 없음
- Candidate means observed unique and nonblank only; it is not a confirmed primary key.

## Major quality evidence

### PRBD01N001

- Columns with observed null/blank: 32
- Highest null/blank columns (max 10): BUY_YIELD#1, CORP_PRETAX_YIELD#1, CORP_AFTER_TAX_YIELD#1, AFTER_TAX_YIELD#1, PREF_TAX_YIELD#1, AVG_ANNUAL_TAX_YIELD#1, DEPO_EQUIV_YIELD_154#1, BUYABLE_QUANTITY#1, CRD_GRD#1, PD_EVCO_CRD_GRD#1
- Columns with leading/trailing whitespace: 6
- Columns with mixed observed types: 13
- Excel error cells: 0
- Explicit schema unit declarations: 0

### PREF01N001

- Columns with observed null/blank: 57
- Highest null/blank columns (max 10): nru_mkt_diff_rt#1, nru_mkt_inav#1, pd_dvid_cycl#1, pd_sect_nm#1, ru_mkt_price#1, ru_mkt_volume#1, cu_base_index#1, cu_charge_rt#1, du_er_1y#1, du_last_aum#1
- Columns with leading/trailing whitespace: 4
- Columns with mixed observed types: 0
- Excel error cells: 0
- Explicit schema unit declarations: 0

### PREF02N001

- Columns with observed null/blank: 34
- Highest null/blank columns (max 10): cu_lev_fector#1, du_diff_rt#1, cu_etn_yn#1, wu_core_yn#1, cu_inverse_short_yn#1, du_last_nav#1, cu_index_repl_mthd#1, cu_index_tracking_yn#1, du_er_1d#1, du_last_aum#1
- Columns with leading/trailing whitespace: 0
- Columns with mixed observed types: 0
- Excel error cells: 0
- Explicit schema unit declarations: 0

### PRFD01N001

- Columns with observed null/blank: 37
- Highest null/blank columns (max 10): itm_eabrv_nm#1, fd_yr5_ern_r#1, fd_yr3_ern_r#1, fd_yr2_ern_r#1, fd_mm18_ern_r#1, fd_yr1_ern_r#1, exchdg_yn#1, fd_mm6_ern_r#1, fd_mm3_ern_r#1, fd_mm1_ern_r#1
- Columns with leading/trailing whitespace: 9
- Columns with mixed observed types: 0
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
