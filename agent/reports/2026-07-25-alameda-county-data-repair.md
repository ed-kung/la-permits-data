# Alameda County data repair

**Summary:** First jurisdiction in `permits_ca_sample.parquet` without an existing repair script was **Alameda County (CA)**. Upstream fields are largely correct when populated (`created`→`FILE_DATE`, `issued`→`PERMIT_DATE`, `closed`→`FINAL_DATE`), but 63 statuses were unmapped, 7 statuses were wrong (including lagging ISS/EXP text with Finaled evidence), one `FILE_DATE` was blank, and 380 Final / closed rows were missing `FINAL_DATE` despite a `Finaled on` search date. The repair script fills or fixes those cases; `PERMIT_DATE` cannot be recovered when `issued` is blank.

## Scope

- **Input:** `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- **Jurisdiction:** Alameda County, CA (2,000 sample rows)
- **Script:** `agent/scripts/ca/data_repair_ca_alameda_county.py`
- **Reference conventions:** `agent/scripts/ny/data_repair_ny_ny.py`

## DATA schemas

Two top-level key-set variants; both expose the same status/date fields:

| INFERRED_SCHEMA | n | Distinguishing keys |
| --- | ---: | --- |
| `project_full` | 1,368 | `inspections`, `permitType`, `work`, … |
| `project_compact` | 632 | `apn` (no inspections block) |

Canonical sources:

| Field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `status` (with Finaled-evidence override) |
| `FILE_DATE` | `created` (fallback: `issued`) |
| `PERMIT_DATE` | `issued` |
| `FINAL_DATE` | `closed`, else Project `search[]` `dateVal` when `datePrefix` contains “final” |

## Findings by field

### STATUS_NORMALIZED

- Distribution before: Final 1,727 · Active 138 · Inactive 52 · In Review 20 · **null 63**
- Nulls were mostly code-enforcement / planning statuses never mapped upstream (`Closed / No Violation`, `Closed / In Compliance`, `REC - Received`, `New Case`, `EXH - Folder/Plans Hold 2+yrs`, `CLR`, etc.).
- One incorrect mapping: `Complaint Received` → Inactive (should be In Review).
- Six rows had lagging status text (`ISS - Issued` ×2, `EXP - Expired` ×4) but `closed` / `Finaled on` evidence → should be Final.

### FILE_DATE

- Matches `created` for 1,999 / 2,000 rows.
- One blank (`BLD2019-00440`): `created` null, but `issued` present → fillable from `issued`.

### PERMIT_DATE

- When present, always matches `issued` (no mismatches).
- 156 blank overall; among Active/Final after status repair, 103 still lack `issued` (12 `APR - Approved` never issued; legacy FIN/CLO shells; code-enforcement Closed / * cases). No safe proxy (`created` ≠ `issued` on ~17% of rows with both dates).

### FINAL_DATE

- When present with `closed`, always matches (1,190 / 1,190).
- 543 Final rows were missing `FINAL_DATE`; 350 of those had Project search `datePrefix=Finaled on` with a usable `dateVal` even though `closed` was null.
- Remaining ~193 Final rows after repair only have `Issued on` / `Created on` (or no Project search entry) and no `closed` → not fillable from DATA.

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 63 | 7 | 63 → **0** |
| `FILE_DATE` | 1 | 0 | 1 → **0** |
| `PERMIT_DATE` | 0 | 0 | 156 → 156 |
| `FINAL_DATE` | 380 | 0 | 810 → 430 |

Status distribution after repair: Final 1,763 · Active 139 · In Review 50 · Inactive 48.

Coverage after repair:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 127 / 139 (91.4%) | 0 / 139 |
| Final | 1,672 / 1,763 (94.8%) | 1,570 / 1,763 (89.1%) |
| In Review | 0 / 50 | 0 / 50 |
| Inactive | 45 / 48 | 0 / 48 |

## Artifacts

- Repair function: `agent/scripts/ca/data_repair_ca_alameda_county.py` (`data_repair`)
- No intermediate datasets written under `AGENT_DATA_PATH`
