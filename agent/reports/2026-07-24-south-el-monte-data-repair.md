# South El Monte (CA) data repair — 2026-07-24

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for South El Monte (first LA-sample jurisdiction lacking a repair script). Wrote `agent/scripts/data_repair_ca_south_el_monte.py`. On the 2,000-row sample: 4 status fills, 65 permit fills, 65 final fills + 5 final fixes; FILE_DATE already complete and correct. Remaining Active/Final date gaps are Accela rows whose status advanced without a matching Permit Issuance / Final Inspection workflow event.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in `permits_la_sample.parquet` order. All earlier CA cities already had `agent/scripts/data_repair_ca_*.py` (including La Cañada Flintridge as `data_repair_ca_la_canada_flintridge.py`). **South El Monte (CA)** was the first without one.

## DATA schema

Single Accela Citizen Access key-set (`tasks_full`, n=2,000): `tasks`, `status`, `date`, `inspections`, `fees_details`, `search_data`, `contacts`, etc.

Useful fields: `DATA.status`, `DATA.date` / `search_data.Date`, workflow `tasks[].events` (`Marked as`, `on` — keys often have leading/trailing spaces).

Canonical date sources:
- **PERMIT_DATE:** `Permit Issuance` / `Issued` (685 events); Closed - Approved amendments use `Modification Review` / `Modification Request Approved`
- **FINAL_DATE:** `Inspection` / `Final Inspection Complete` (latest); fallback `Certificate of Occupancy` / `Final CO Issued`; Closed - Approved → Modification Request Approved

## Field assessment

### STATUS_NORMALIZED

Before: In Review 938, Active 409, Final 391, Inactive 258, missing 4.

`STATUS_ORIGINAL` matches `DATA.status` (case-insensitive) on all non-blank rows. Existing normalization is consistent with Accela status:

| DATA.status | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Inspection Phase | Active | 409 |
| Closed - Complete / Closed - Approved / Pending CO | Final | 309 / 66 / 16 |
| Closed - Withdrawn / Denied / Permit Expired | Inactive | 239 / 17 / 2 |
| Fees Due, In Review, Pending, Plan Review, … | In Review | 938 |

Issues:
- **4 blank** `DATA.status` (Residential Sewer/Septic, Application Intake TBD only) → filled as **In Review**.
- No incorrect non-missing statuses relative to `DATA.status`. Stale Accela statuses (e.g. Ready to Issue / Fees Due after Issued; Inspection Phase after Final Inspection Complete) are left as-is; workflow is not used to override status.

### FILE_DATE

0 missing; all 2,000 match `DATA.date`. No repairs.

### PERMIT_DATE

1,317 missing. Ideal: populated for Active and Final.

- When both present, existing PERMIT_DATE always matches `Permit Issuance` / `Issued` (372 Active + 305 Final).
- **65 FILLED:** 65 of 66 Closed - Approved Amendment / Permit Extension rows from Modification Request Approved (1 Amendment lacks that event).
- **Not fillable (58 Active/Final):** 37 Inspection Phase and 19 Closed - Complete (+ 1 Pending CO, 1 Closed - Approved) with empty/TBD Permit Issuance — status set without an Issued event.

### FINAL_DATE

1,678 missing. Ideal: populated for Final.

- Canonical `Inspection` / `Final Inspection Complete` (latest); 301 Closed - Complete + 16 Pending CO already matched.
- **65 FILLED** from Modification Request Approved on Closed - Approved.
- **1 FIXED** to a later Final Inspection Complete (2023-04-19 → 2023-07-20).
- **4 FIXED (cleared):** spurious FINAL_DATE on non-Final (3 Inspection Phase, 1 Ready to Issue) where Final Inspection Complete fired but `DATA.status` never advanced to Closed/Pending CO.
- **Not fillable (8 Final):** Closed - Complete / one Closed - Approved with no Final Inspection, Final CO, or Modification Approved event.

## Repair performance (n=2,000)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 4 | 0 | 4 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 65 | 0 | 1,317 → 1,252 |
| FINAL_DATE | 65 | 5 | 1,678 → 1,617 |

After repair, PERMIT_DATE coverage: Active 91.0%, Final 94.6%. FINAL_DATE coverage: Final 98.0%; non-Final 0%.

## Artifacts

- Script: `agent/scripts/data_repair_ca_south_el_monte.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/south_el_monte_repaired_sample.parquet`
