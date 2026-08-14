# Redington Shores (FL) data repair

**Summary:** Redington Shores uses a SmartGov portal payload (`Build Status` + nested `My Project` dates). The main defect is mass-null `STATUS_NORMALIZED` (1,615 / 2,000) when `Build Status` / `STATUS_ORIGINAL` were not scraped, even though `My Project` still carries Submitted / Issued / Closed. The repair fills status from Build Status with Closed/Issued date overrides, sets `FILE_DATE` from Submitted (fallback Created), `PERMIT_DATE` from Issued (fallback Approved), and `FINAL_DATE` from Closed. After repair, Active/Final have 100% `PERMIT_DATE` and Final has 100% `FINAL_DATE`; only 7 empty SmartGov shells remain without status.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_fl_sample.parquet` without
`agent/scripts/{state}/data_repair_{state}_{city}.py`: **Redington Shores, FL**.

## Data / schema

- Sample size: **2,000** rows
- Portal family: SmartGov (same pattern as Longwood / Lighthouse Point)
- `INFERRED_SCHEMA` counts after repair:
  - `smartgov_no_desc`: 1,603
  - `smartgov_full`: 389
  - `smartgov_empty`: 8

Canonical `DATA` sources:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `Build Status` + Closed/Issued date overrides; null Build Status → date inference |
| `FILE_DATE` | `My Project.Submitted` (fallback `Created`) |
| `PERMIT_DATE` | `My Project.Issued` (fallback `Approved`) |
| `FINAL_DATE` | `My Project.Closed` (fallback passed Final/COO inspection) |

## Findings by field

### STATUS_NORMALIZED

- Before: 1,615 null; remainder mostly `closed→Final`, `issued→Active`, plus a few review/expired/disapproved labels.
- Root cause: scrape often left `Build Status` / `STATUS_ORIGINAL` null while `My Project` still had dates; also lag (e.g. Closed still labeled Active/In Review; Expired still Active; Disapproved still In Review).
- Repair: FILLED 1,608; FIXED 59. After: Active 661, Final 442, In Review 871, Inactive 19, null 7 (empty shells).

### FILE_DATE

- Before: 8 missing. Of those with payload, 1,991/1,992 existing values already matched `Submitted`.
- Repair: FILLED 1 (from Submitted/Created). 7 empty shells remain missing.

### PERMIT_DATE

- Before: 956 missing. When present, always matched `Issued` (0 mismatches).
- 15 rows had `Issued` but null `PERMIT_DATE`; many Closed/Issued null-status rows needed fills after status inference.
- Repair: FILLED 67. Active/Final → 100% populated; In Review correctly remains 0%.

### FINAL_DATE

- Before: 1,600 missing. When present and Closed existed, always matched Closed (0 mismatches); 42 Closed dates were not copied into `FINAL_DATE`.
- Repair: FILLED 42. Final → 100% populated; non-Final rows keep null `FINAL_DATE`.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1,608 | 59 | 1,615 | 7 |
| FILE_DATE | 1 | 0 | 8 | 7 |
| PERMIT_DATE | 67 | 0 | 956 | 889 |
| FINAL_DATE | 42 | 0 | 1,600 | 1,558 |

Coverage after repair:

- `FILE_DATE`: 100% for Active / Final / In Review / Inactive
- `PERMIT_DATE`: 100% Active, 100% Final, 0% In Review
- `FINAL_DATE`: 100% Final, 0% non-Final
- Date order violations (`FILE>PERMIT`, `PERMIT>FINAL`, `FILE>FINAL`): **0**

Not repairable: 8 `smartgov_empty` shells with no Build Status, permit identity, or My Project dates (7 still null status / dates).

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_redington_shores.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_redington_shores_repaired.parquet`
