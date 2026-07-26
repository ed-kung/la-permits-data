# Huntington Beach (CA) data repair

**Summary:** Among CA sample jurisdictions, Huntington Beach was the first `(JURISDICTION, STATE)` pair without a repair script. Its DATA JSON is an Accela Citizen Access payload with two key-set variants (`accela_full` / `accela_basic`). `FILE_DATE` already matched `search_data.Date` / `DATA.date` for all 1,999 rows. Status repair filled 41 previously unmapped Accela statuses and fixed 39 incorrect labels (mostly Finaled still labeled Active, Archived labeled In Review, and Issued labeled In Review). `PERMIT_DATE` gained only 3 fills from `Permit Issuance` / `Open` Issued events; most Active/Final gaps lack an issuance task. `FINAL_DATE` was the main win: 881 Final gaps filled from `Closed`/`Close` or Approved Final* inspections, and 41 spurious Active `FINAL_DATE` values cleared. After repair, Final `FINAL_DATE` coverage is 78.5% (1,003 / 1,277).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Huntington Beach, CA** (1,999 rows) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/ca/data_repair_ca_huntington_beach.py`
- Artifact: `AGENT_DATA_PATH/huntington_beach_repaired_sample.parquet`

## DATA schema

Every record has `date`, `tasks`, `status`, `address`, `details`, `contacts`, `job_value`, `valuation`, `total_fees`, `record_type`, `search_data`, `more_details`, and `address_lines`. Canonical fields:

| DATA field | Target column |
| --- | --- |
| `DATA.status` | `STATUS_NORMALIZED` |
| `search_data.Date` / `DATA.date` | `FILE_DATE` |
| `Permit Issuance` / `Issued` (fallback `Open` / `Issued`) | `PERMIT_DATE` |
| `Closed` / `Close*` (fallback Approved Final* `inspections[].Status Date`) | `FINAL_DATE` |

`INFERRED_SCHEMA` variants (same repair logic):

- `accela_full` — 1,272 rows (`+ conditions`, `inspections`, `fees_details`, `related_records`)
- `accela_basic` — 727 rows (workflow / search fields only)

Status map from `DATA.status`: Finaled/Final/Closed/Complete(d)/Granted/Recorded/Released → Final; Issued/Approved/Active/Enrolled → Active; Expired*/Cancelled/Void/Denied/Inactive/Archived/Do Not Inspect → Inactive; Pending*/Submitted/Incomplete/Accepted/In Review/Plans Routed → In Review.

## Field assessment

### STATUS_NORMALIZED

- **Missing before:** 42 / 1,999 (Do Not Inspect 12, Enrolled 15, Pending Self-Correct 11, Plans Routed 2, Released 1, plus 1 blank-status Conditional Use Permit)
- **Correctness:** Mostly aligned with `STATUS_ORIGINAL`, but `STATUS_ORIGINAL` lagged live `DATA.status` on 18 rows. Notable errors:
  - 12× `DATA.status=Finaled` with `STATUS_ORIGINAL=issued` → labeled **Active** (should be Final)
  - 2× `DATA.status=Issued` with `STATUS_ORIGINAL=incomplete` / `pending payment` → labeled **In Review** (should be Active)
  - 25× `Archived` labeled **In Review** (should be Inactive)
- **Repair:** **41 FILLED**, **39 FIXED** · missing after: 1 (blank `DATA.status`)
- After: Final 1,277 · Active 322 · Inactive 299 · In Review 100 · null 1

### FILE_DATE

- **Missing:** 0 / 1,999
- **Correctness:** Calendar-day match to `search_data.Date` / `DATA.date` for all rows. `Application Submittal` / `Accepted` differs on 141 rows (usually ±1–2 days) and was not treated as authoritative.
- **Repair:** 0 FILLED, 0 FIXED (already complete)

### PERMIT_DATE

- **Missing before:** 433 / 1,999
- **Correctness:** Where both `PERMIT_DATE` and a Permit Issuance / Issued event exist (1,566), they always match. No incorrect populated values found.
- **Fillable:** 3 Active/Final rows with Issued task events but blank `PERMIT_DATE` (including 1 `Open`/`Issued` and rows remapped to Active/Final)
- **Repair:** **3 FILLED**, **0 FIXED** · missing after: 430
- Post-repair coverage: Active 58.4% (188/322); Final 93.3% (1,192/1,277)
- **Not fillable:** ~200 Active/Final gaps — Approved revisions, Active occupancy shells, Closed environmental / CofO / Complete records, and legacy Issued Certificate of Occupancy rows with empty Permit Issuance history
- Edge case left as-is: 1 Incomplete (In Review) Encroachment still carries a matching Permit Issuance Issued date while `DATA.status` remains Incomplete

### FINAL_DATE

- **Missing before:** 1,836 / 1,999
- **Correctness:** Where both exist and a Closed/Close date is present, they match. 41 Active (`Issued`) rows incorrectly carried `FINAL_DATE` from a Closed task while `DATA.status` remained Issued.
- **Fillable Final gaps:** ~749 from Closed/Close + ~132 from Approved Final* inspections (including `Approved - Issue CofO`)
- **Repair:** **881 FILLED**, **41 FIXED** (cleared non-Final) · missing after: 996
- Post-repair: Final 78.5% (1,003 / 1,277); Active / In Review / Inactive all 0%
- **Not fillable:** ~274 Final rows — Finaled shells with empty Closed events and no usable Final* inspection, plus Completed planning/zoning letters whose Closed date is the Accela sentinel `12/31/9999`

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 41 | 39 | 42 | 1 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 3 | 0 | 433 | 430 |
| FINAL_DATE | 881 | 41 | 1,836 | 996 |

Root cause of status errors: pipeline normalized from stale `STATUS_ORIGINAL` (and an incomplete status vocabulary) rather than current `DATA.status`. Date fields that were already populated were consistent with Accela task events; the large Final `FINAL_DATE` gain comes from reading Closed/Close workflow dates and Final* inspection approvals that the upstream extract left blank. Remaining Active `PERMIT_DATE` gaps and Final `FINAL_DATE` gaps reflect empty Accela histories / sentinel dates, not mapping bugs. Net `FINAL_DATE` missing falls sharply despite clearing 41 spurious Active dates.
