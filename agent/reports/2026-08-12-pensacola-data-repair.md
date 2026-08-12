# Pensacola (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Lake County in list order) was **Pensacola**. DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`). `STATUS_NORMALIZED` already matched portal status on every row; `FILE_DATE` already matched `DateCreated` on all 2,000 rows. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py` (slug via `[^a-z0-9]+` → `_`). First missing: **Pensacola, FL** (index 61 after Lake County) → `agent/scripts/fl/data_repair_fl_pensacola.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,082 | Includes `PaymentProcessorModule` (value `MGO`) |
| `mgo_base` | 918 | Same flat key set without that key |

No nested inspections/fees objects. `TypeList` is a fee-description string (995 rows are `"Unknown"`); no `Imported Fee` shells in this sample.

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
| Closed | 1,298 | Final | Correct |
| Issued | 93 | Active | Correct |
| Open | 46 | In Review | Correct (`Open` is distinct from `Issued`; no real `DateIssued`) |
| In Review | 31 | In Review | Correct |
| Expired | 517 | Inactive | Correct |
| Cancelled | 15 | Inactive | Correct |

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0.

### FILE_DATE

- Before: missing on **0 / 2,000** rows.
- Source: `DateCreated` — calendar-day match on all 2,000 rows (`FILE_DATE` date == `DateCreated[:10]`).
- After: still 0 missing; no fills or fixes.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0.

### PERMIT_DATE

- Before: missing on **all 2,000** rows, including all Active (93) and Final (1,298).
- Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row.
- `DateUpdated`, `ScheduledDueDate`, and power-request dates are likewise null/sentinel.
- Root cause: MGO extract does not populate issuance timestamps in this city sample (same pattern as Santa Rosa County / Escambia County).

**Repair performance:** FILLED 0, FIXED 0; missing 2,000 → 2,000. Script will fill from a real `DateIssued` if present in future extracts. Active/Final coverage: 0%.

### FINAL_DATE

- Before: missing on **all 2,000** rows, including every Final (`Closed`) record.
- Payload has no finaled / completion / CO timestamp; `DateUpdated` is always the `.NET` sentinel.

**Repair performance:** FILLED 0, FIXED 0; missing 2,000 → 2,000. Final coverage: 0%.

## Ideal-field checklist (after repair)

| Rule | Result |
| --- | --- |
| FILE_DATE populated for all records | Yes (100%) |
| PERMIT_DATE for Active and Final | No (0% — not in DATA) |
| FINAL_DATE for Final | No (0% — not in DATA) |

Status distribution unchanged: Final 1,298; Inactive 532; Active 93; In Review 77.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_pensacola.py`
- Repaired sample: `$AGENT_DATA_PATH/pensacola_repaired_sample.parquet`
