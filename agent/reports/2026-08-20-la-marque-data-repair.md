# La Marque (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, La Marque was first. Its DATA is a SmartGov portal payload (`smartgov_minimal` / `smartgov_empty`). Of 2,000 sample rows, 1,973 are empty scraped shells and cannot be repaired. Among the 27 usable rows, status was filled once (null Build Status + Submitted date → In Review) and fixed three times (Pending with an Issued date → Active). FILE_DATE, PERMIT_DATE, and FINAL_DATE already matched My Project on usable rows; one Final burial permit still lacks PERMIT_DATE because Issued/Approved are blank.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **La Marque, TX** (2,000 sample rows).

## DATA schema

All 2,000 rows share the same top-level SmartGov key set (`Department`, `My Project`, `Build Status`, `Permit Number`, `Permit Type`, contacts/fees/inspections/parcels, `Application Number`). Usability is determined by whether those fields are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `smartgov_empty` | 1,973 | Blank shell; UUID-like `PERMIT_NUMBER`; no status/dates in DATA |
| `smartgov_minimal` | 27 | Usable Build Status and/or My Project dates / Permit Type |

Relevant fields:

| DATA field | Role |
| --- | --- |
| `Build Status` | Raw status (`Issued`, `Pending`, `All work completed`, `Expired: …`) |
| `My Project.Submitted` / `Created` | Application / file date → `FILE_DATE` |
| `My Project.Issued` / `Approved` | Issue / approval date → `PERMIT_DATE` |
| `My Project.Closed` | Completion / final date → `FINAL_DATE` |
| `Permit Inspections` | Fallback final date (passed Building Final / COO) |

## Field assessment

### STATUS_NORMALIZED

| `Build Status` | Pre-repair `STATUS_NORMALIZED` | n |
| --- | --- | ---: |
| Issued | Active | 7 |
| All work completed | Final | 6 |
| Pending | In Review | 6 |
| Expired: … | Inactive | 7 |
| (null, usable row) | missing | 1 |
| (empty shell) | missing | 1,973 |

- Missing before: **1,974 / 2,000** (98.7%)
- Among rows with Build Status, the pre-existing mapping was already correct for Issued / All work completed / Expired / Pending-without-Issued
- **Fillable:** 1 row with Permit Type + Submitted/Created but null Build Status → In Review from dates
- **Incorrect:** 3 Pending rows also carry `My Project.Issued` → should be Active (Issued-date override, same convention as Bellaire/Anna SmartGov repairs)
- Empty shells: **not fillable** from DATA

### FILE_DATE

- Missing before: **1,973 / 2,000** (all empty shells)
- On all 27 usable rows, `FILE_DATE` already equals calendar day of `Submitted` (fallback `Created`)
- Ideal coverage met for usable payload; empty shells remain missing

### PERMIT_DATE

- Missing before: **1,980 / 2,000**
- Usable Active rows: all already match `Issued`
- Usable Final: 5/6 match `Issued`; **BU2019-003** has Closed but blank Issued/Approved → cannot fill
- Usable Inactive: 5/7 have Issued (kept); 2 Expired rows never issued → stay missing
- After Pending→Active fixes, those three already had correct Issued-based `PERMIT_DATE`
- Empty shells: not fillable

### FINAL_DATE

- Missing before: **1,994 / 2,000**
- All 6 Final rows already have `FINAL_DATE` = `My Project.Closed`
- No spurious `FINAL_DATE` on non-Final rows
- Empty shells / non-Final: correctly missing

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_la_marque.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA` (`smartgov_minimal` / `smartgov_empty` / `missing` / `unknown`)
- Overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED` when changed
- Status map includes La Marque’s `All work completed` → Final and sticky `Expired*` → Inactive
- Issued-date override promotes Pending (+ Issued) → Active
- Dates: Submitted/Created → FILE; Issued/Approved → PERMIT; Closed / final inspection → FINAL

## Repair performance (TX sample, n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1 | 3 | 1,974 | 1,973 |
| FILE_DATE | 0 | 0 | 1,973 | 1,973 |
| PERMIT_DATE | 0 | 0 | 1,980 | 1,980 |
| FINAL_DATE | 0 | 0 | 1,994 | 1,994 |

Status changes:

| Before | After | n | Reason |
| --- | --- | ---: | --- |
| (missing) | In Review | 1 | Null Build Status; Submitted/Created present |
| In Review | Active | 3 | Pending Build Status but Issued date set (BU2012-004, BU2014-002, BU2015-001) |

Coverage after repair (usable schemas only, n=27):

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- |
| Active (10) | 100% | 100% | 0% |
| Final (6) | 100% | 83.3% | 100% |
| In Review (4) | 100% | 0% | 0% |
| Inactive (7) | 100% | 71.4% | 0% |

Remaining gaps (source limitations):

- 1,973 empty SmartGov shells → status and all dates stay missing
- Final `BU2019-003`: no Issued/Approved → `PERMIT_DATE` stays missing
- 2 Expired rows never issued → `PERMIT_DATE` stays missing (acceptable for Inactive)

Date-order violations after repair: none.

## Artifact

- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_la_marque_repaired.parquet`
