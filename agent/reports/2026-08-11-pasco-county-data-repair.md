# Pasco County (FL) data repair

Summary: Pasco County was the first FL sample jurisdiction without a repair script after Jacksonville, Lee County, Sarasota County, Osceola County, Orlando, and Charlotte County. Accela Citizen Access payloads expose status under `DATA.status` and dates under `DATA.date`, Permit Issuance / Closed / Permit Completion Review task events, and inspection Status Dates. The repair remaps 17 statuses (2 FILLED, 15 FIXED) where `STATUS_ORIGINAL` lagged Accela, leaves `FILE_DATE` unchanged (already 100% populated and correct), recovers **327** missing `PERMIT_DATE` values and corrects **46** incorrect ones from issuance workflow, and recovers **922** missing `FINAL_DATE` values while correcting **165** (often replacing final-inspection Pass with later Final Release / Closed). After repair, Final rows have **95.6%** `FINAL_DATE` coverage; remaining gaps are mostly legacy `accela_shell` Closed/Complete rows with no dated issuance or finalization history, plus 168 empty-status stubs.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Pasco County, FL**
- Sample size: **2,002** records
- Script: `agent/scripts/fl/data_repair_fl_pasco_county.py` (`data_repair`)

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `accela_shell` | 1,258 | Tasks present but no dated events (legacy / migrated histories; often still have `inspections`) |
| `accela_full` | 739 | Accela payload with `inspections` and at least one dated task event |
| `accela_basic` | 5 | Dated task events without an `inspections` array |

Canonical field sources:

- `DATA.status` → `STATUS_NORMALIZED`
- `DATA.date` / `search_data.Date` → `FILE_DATE`
- Earliest Permit Issuance / Permit Issued Marked as Permit Issued / Issued (else Application Submittal Marked as Permit Issued / Issue Permit) → `PERMIT_DATE`
- Permit Completion Review Final Release / Final CO/CC/Meter Release; else Closed / Case Complete; else Inspection Final Inspection Complete; else final inspection Pass Status Date → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,612; missing 170; In Review 106; Inactive 98; Active 16.
- Upstream `STATUS_NORMALIZED` follows `STATUS_ORIGINAL`, which lags `DATA.status` on **15** rows (e.g. ORIG=`permit issued` / `conditional approval` / `pending client` while Accela shows `Closed` / `Abandoned` / `Expired Permit` / `Issued`).
- Of 170 null statuses, **168** have empty `DATA.status` (thin `accela_shell` stubs, typically `FILE_DATE` 2016-04-08 with empty search Status/Action and empty tasks) → not fillable. **2** were fillable (`Abandoned`→Inactive, `Active Mainframe`→Active).
- Repair using `DATA.status`:
  - **2 FILLED**
  - **15 FIXED** — mainly lagged Closed Active/In Review/Inactive→Final (11), Abandoned/Expired Permit→Inactive (2), Issued/Permit Issued lags→Active (2)
- After repair: Final 1,623; missing **168**; Inactive 100; In Review 98; Active 13.
- Remaining missing: all 168 have empty `DATA.status` → not fillable from DATA.

### FILE_DATE

- Before: **0 missing (0.0%)**. All 2,002 values already matched parseable `DATA.date` at day resolution.
- Repair: **0 FILLED**, **0 FIXED**.
- After: still fully populated for every non-null status bucket (100%).

### PERMIT_DATE

- Before: 1,671 missing (83.5%). Among Active/Final, coverage was weak (Active 13/16; Final 294/1,612).
- Accela issuance signals: Permit Issuance Marked as Permit Issued (363); Application Submittal Marked as Permit Issued / Issue Permit (366) on older workflows with no Permit Issuance event.
- Existing `PERMIT_DATE` agreed with Accela issuance on **284** rows and disagreed on **46** (upstream often a few days earlier than the Issued event).
- Repair: **327 FILLED** for Active/Final rows with an issuance event but null permit; **46 FIXED** to the Accela Issued date.
- After repair: Active **12/13 (92.3%)**; Final **627/1,623 (38.6%)**.
- Remaining Active/Final gaps (**997**): almost all `accela_shell` Complete/Closed rows with empty task event histories (no issuance mark). One Active Mainframe legacy row also has no issuance event. Not fillable from DATA.

### FINAL_DATE

- Before: 1,370 missing (68.4%). Among rows that had `FINAL_DATE`, most matched Inspection Marked as Final Inspection Complete / final inspection Pass (**~583 / ~497**), while Closed task dates matched only **73**.
- Stronger finaled/signoff signals when present: Permit Completion Review Final Release / Final CO/CC/Meter Release; Closed / Case Complete Marked as Closed; then inspection completion.
- Spurious finals: **2** Active (`Permit Issued`) rows carried a `FINAL_DATE` → cleared.
- Repair: **922 FILLED** (including shell Final rows filled from passed Final / trade inspection Status Dates), **165 FIXED** (prefer Final Release / Closed over earlier inspection Pass when available; clear non-Final spurious dates).
- After: Final **1,552/1,623 (95.6%)**; Active / In Review / Inactive have **0**.
- Remaining Final gaps (**71**): all `accela_shell` Closed (69) / Complete (2) with neither dated completion/Closed events nor a usable passed inspection Status Date.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 2 | 15 | 170 | 168 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 327 | 46 | 1,671 | 1,344 |
| FINAL_DATE | 922 | 165 | 1,370 | 450 |

Coverage after repair (share non-null):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 13 | 100% | 92.3% | 0% |
| Final | 1,623 | 100% | 38.6% | 95.6% |
| In Review | 98 | 100% | 1.0% | 0% |
| Inactive | 100 | 100% | 18.0% | 0% |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_pasco_county.py`
- Summary JSON: `AGENT_DATA_PATH/pasco_county/repair_summary.json`
