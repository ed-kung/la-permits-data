# Arlington (TX) data repair — STATUS_NORMALIZED and dates

**Summary:** Among TX sample jurisdictions ordered by name, Arlington is the first without an existing repair script (Abilene, Allen, and Anna already covered). Arlington’s `DATA` JSON has two portal families (`underscore_*` and `spaced_*`) plus 312 null scrapes. Status and application/issue dates are already correct when DATA exists. The main defects are 262 spurious `FINAL_DATE` values on non-Final spaced rows (copied from `Expiry Date`) and one `PERMIT_DATE` that disagrees with `Issued`. Underscore `Finaled` rows have no completion date in DATA, so most Final records remain without `FINAL_DATE`.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` (193,630 rows). Walking `(JURISDICTION, STATE)` alphabetically, existing TX scripts cover Abilene, Allen, and Anna. **Arlington** is the first gap → `agent/scripts/tx/data_repair_tx_arlington.py`.

Sample size: **2,001** Arlington records.

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Distinguishing keys |
| --- | ---: | --- |
| `underscore_work_sub` | 710 | `STATUS`, `Application_Date`, `Issue_Date`, `WORK`/`Sub` |
| `spaced_core` | 428 | `Status`, `Application Date`, `Issued`, `Expiry Date` |
| `missing` | 312 | no usable DATA |
| `underscore_zoning` | 104 | + `Zoning_District` / `FDesc` |
| `spaced_zoning` | 73 | + `Zoning District` |
| `spaced_sewer` | 62 | + sewer-service question |
| `underscore_folderrsn` | 58 | + `FOLDERRSN` |
| `underscore_construction` | 58 | + construction sqft/valuation |
| `spaced_minimal` | 53 | spaced dates/status, no `Address` |
| `underscore_minimal` | 53 | underscore dates/status, no WORK/Sub |
| `spaced_event` | 51 | + event start/end dates |
| `spaced_valuation` | 20 | + construction valuation (no zoning district) |
| `underscore_building` | 19 | + `Building_SqFt` |

Repair uses the same status/date fields within each family.

## Field assessment (before repair)

### STATUS_NORMALIZED

Upstream mapping from `STATUS_ORIGINAL` / DATA status is correct for all 2,001 rows (no nulls).

| DATA raw | → | STATUS_NORMALIZED |
| --- | --- | --- |
| Finaled | → | Final |
| Issued / Active | → | Active |
| Expired / InActive / Void | → | Inactive |
| Pending | → | In Review |

Cross-check vs DATA: **0 mismatches**, **0 fillable nulls**.

### FILE_DATE

- Present: **1,689** — all match `Application_Date` / `Application Date` at day resolution
- Missing: **312** — exactly the `missing` DATA rows; not fillable from DATA

### PERMIT_DATE

- Present values almost always match `Issue_Date` / `Issued`
- **1 FIXED candidate:** Active row with `Issued=03/18/2024` but `PERMIT_DATE=2023-09-01`
- **1 unfillable:** Active zoning-verification row with blank `Issued` (and null `PERMIT_DATE`)
- Ideal coverage for Active/Final already ~99.9%+ where an issue date exists

### FINAL_DATE

- **No completion/signoff date field** exists in either DATA family
- Final rows with `FINAL_DATE`: **167 / 925** — all are `missing` DATA scrapes that already carry a final date upstream; left unchanged (cannot verify from DATA)
- Final rows without `FINAL_DATE`: **758** — all underscore `Finaled`; not fillable
- **Incorrect extras on non-Final:** 247 Active + 15 Inactive spaced rows — **260/262 equal `Expiry Date`** (expiration, not finalization). Reason: upstream copied expiry into `FINAL_DATE`

## Repair behavior

Canonical mappings:

- `STATUS` / `Status` → `STATUS_NORMALIZED`
- `Application_Date` / `Application Date` → `FILE_DATE`
- `Issue_Date` / `Issued` → `PERMIT_DATE` (whenever present)
- No DATA final-date candidate → do not fill `FINAL_DATE`; clear it when effective status is not Final

Flags: `FILLED` for former missings; `FIXED` for corrected or cleared values. `INFERRED_SCHEMA` set per row.

## Performance (after repair)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 312 → 312 |
| PERMIT_DATE | 0 | 1 | 1 → 1 |
| FINAL_DATE | 0 | 262 | 1,572 → 1,834 |

Status distribution unchanged: Active 987, Final 925, Inactive 88, In Review 1.

Date coverage after repair:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 986 / 987 (99.9%) | 0 / 987 |
| Final | 925 / 925 (100%) | 167 / 925 (18.1%) |
| In Review | 1 / 1 (100%) | 0 / 1 |
| Inactive | 88 / 88 (100%) | 0 / 88 |

`FILE_DATE`: 1,689 / 2,001 (all records with DATA).

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_arlington.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_arlington_repaired.parquet`
