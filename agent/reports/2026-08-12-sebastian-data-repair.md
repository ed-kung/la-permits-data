# Sebastian (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Sebastian**. DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`). `STATUS_NORMALIZED` already matched portal status on every row; `FILE_DATE` already matched `DateCreated` on all 2,000 rows. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py` (slug via `[^a-z0-9]+` → `_`). First missing: **Sebastian, FL** → `agent/scripts/fl/data_repair_fl_sebastian.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,611 | Includes `PaymentProcessorModule` (value `MGO`) |
| `mgo_base` | 389 | Same flat key set without that key |

No nested inspections/fees objects. All rows have `ProjectType == "Permit"`. `TypeList` holds fee-description strings (e.g. DBPR-BCAIB Surcharge, Electric Master).

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` (whitespace-stripped) |
| FILE_DATE | `DateCreated` |
| PERMIT_DATE | `DateIssued` when not `0001-01-01` (never in sample) |
| FINAL_DATE | *(none)* — `DateUpdated` also always sentinel |

`STATUS_ORIGINAL` matches live `ProjectStatus` on all 2,000 rows (case-normalized).

## Field assessments

### STATUS_NORMALIZED

Upstream mapping was already correct for all 2,000 rows:

| ProjectStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Project Closed/Complete | 1,759 | Final | Correct |
| Expired | 167 | Inactive | Correct |
| Permit Issued | 46 | Active | Correct |
| Pending (Under Review) | 27 | In Review | Correct |
| Void | 1 | Inactive | Correct |

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0.

### FILE_DATE

- Before: missing on **0 / 2,000** rows.
- Source: `DateCreated` — calendar-day match on all 2,000 rows.
- After: still 0 missing; no fills or fixes.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0.

### PERMIT_DATE

- Before: missing on **all 2,000** rows, including all Active (46) and Final (1,759).
- Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row.
- `DateUpdated`, `ScheduledDueDate`, and power-request dates are likewise null/sentinel.
- Root cause: MGO extract does not populate issuance timestamps in this city sample (same pattern as Crestview / Pensacola / Santa Rosa County / Escambia County).

**Repair performance:** FILLED 0, FIXED 0; missing 2,000 → 2,000. Script will fill from a real `DateIssued` if present in future extracts. Active/Final coverage: 0%.

### FINAL_DATE

- Before: missing on **all 2,000** rows, including every Final (`Project Closed/Complete`) record.
- Payload has no finaled / completion / CO timestamp; `DateUpdated` is always the `.NET` sentinel.

**Repair performance:** FILLED 0, FIXED 0; missing 2,000 → 2,000. Final coverage: 0%.

## Ideal-field checklist (after repair)

| Rule | Result |
| --- | --- |
| FILE_DATE populated for all records | Yes (100%) |
| PERMIT_DATE for Active and Final | No (0% — not in DATA) |
| FINAL_DATE for Final | No (0% — not in DATA) |

Status distribution unchanged: Final 1,759; Inactive 168; Active 46; In Review 27.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_sebastian.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_sebastian_repaired.parquet`
