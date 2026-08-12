# Clay County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Clay County**. DATA splits into a legacy county portal (`Permit Information`, 1,608 rows) and Tyler EnerGov (`entity`/`details`, 391 rows). The largest defect was STATUS_NORMALIZED: **957** closed/admin-closed/voided rows labeled Final were remapped to Inactive (no completion/CO), plus **5** issued-but-`opened` rows In Review→Active and **1** EnerGov `Approved` with FinalDate→Final. FILE_DATE was already complete on EnerGov; legacy has no ApplyDate, so only **86** weak fills from notes/plan reviews. FINAL_DATE gained **250 FILLED** / **197 FIXED** (prefer `co_date` over inspection stamps; clear **4** spurious non-Final values). After repair: EnerGov FILE_DATE 100%, Active PERMIT_DATE **99.4%**, Final PERMIT_DATE **100%**, Final FINAL_DATE **100%**, non-Final FINAL_DATE **0**. Legacy FILE_DATE remains mostly missing (5.3%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in first-appearance order. Existing scripts covered Jacksonville through Manatee County; **Clay County** was the first without `agent/scripts/fl/data_repair_fl_clay_county.py`.

Sample size: **1,999** records.

## DATA schemas

| INFERRED_SCHEMA                 | Count |
| ------------------------------- | ----: |
| `legacy_admin_closed`           |   941 |
| `legacy_issued_co`              |   612 |
| `energov_issued_finaled`        |   131 |
| `energov_issued`                |   124 |
| `energov_applied`               |    63 |
| `legacy_issued_closed`          |    47 |
| `energov_full_issued`           |    46 |
| `energov_full_applied`          |    20 |
| `energov_full_issued_finaled`   |     7 |
| `legacy_issued_open`            |     5 |
| `legacy_voided`                 |     3 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | legacy: `close_type` / `is_closed` / `void_date` / `issue_date`; energov: `CaseStatus` (+ FinalDate for `Approved`) |
| FILE_DATE         | energov `ApplyDate`; legacy earliest Permit Note `created_on` or Plan Review `received_date` |
| PERMIT_DATE       | legacy `issue_date` / energov `IssueDate` (years outside 1980–2035 / `0001-01-01` treated as missing) |
| FINAL_DATE        | legacy `co_date` else last approved final-ish / approved inspection; energov `FinalDate` / `FinalizeDate` (Final only) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,749 · Active 159 · In Review 67 · Inactive 24 · missing 0.

- EnerGov `CaseStatus` already agreed with `STATUS_ORIGINAL` / `STATUS_NORMALIZED` for Issued / Complete / In Review / Expired / etc.
- Main upstream error: treating terminal **Admin Closed** (and legacy **Permit Voided**) as Final despite no CO/completion date — same pattern repaired in Palm Beach County / Bradenton.
- **963 FIXED**:
  - `closed` → Inactive: **944** (941 `Admin Closed` + 3 `Permit Voided`)
  - `admin closed` → Inactive: **13** (EnerGov)
  - `opened` (issued, `is_closed=False`) In Review → Active: **5**
  - `approved` Active → Final (usable `FinalDate`): **1**
- **0 FILLED** (no null statuses in sample).

After: Inactive 981 · Final 793 · Active 163 · In Review 62 · missing 0.  
Flags: **FILLED 0 · FIXED 963**.

### FILE_DATE

Before: 1,608 missing (100% of legacy; 0% of EnerGov). Ideal: populated for all records.

- EnerGov: FILE_DATE already matched `ApplyDate` on **391 / 391** rows.
- Legacy portal has no application/submittal field. **86 FILLED** from earliest usable note `created_on` or plan-review `received_date` (often same-day as issue).
- Remaining **1,522** legacy rows have no repairable FILE_DATE in DATA.

After: 1,522 missing (23.9% overall; **100%** EnerGov; **5.3%** legacy).  
Flags: **FILLED 86 · FIXED 0**.

### PERMIT_DATE

Before: 83 missing. Ideal: populated for Active and Final.

- When both present and plausible, PERMIT_DATE already matched `issue_date` / `IssueDate`.
- **8 FIXED**: cleared sentinel `0001-01-01` / `1900-01-01` PERMIT_DATE on Admin Closed rows (no usable issue date in DATA) → now Inactive with null PERMIT_DATE.
- Remaining Active gap: **1** EnerGov `Issued` shell (`ELR0323-0860`) with `IssueDate=null` / `details.Issued=False`.

After: 91 missing. Coverage: Active **99.4%** (162/163); Final **100%** (793/793).  
Flags: **FILLED 0 · FIXED 8**.

### FINAL_DATE

Before: 1,452 missing; Final coverage 542/1,749 (31.0%). Ideal: populated for Final.

- Upstream often stored an approved-inspection date while leaving `co_date` unused, or left FINAL_DATE null when `co_date` was present (**289** fillable from CO alone among pre-repair Final).
- **250 FILLED** on rows that remain Final (CO date or approved inspection).
- **197 FIXED** to prefer `co_date` over a differing inspection-derived stamp; **2** sentinel `1900-01-01` values replaced/cleared as part of fixes.
- **4 FIXED** cleared spurious FINAL_DATE on non-Final EnerGov rows (`Issued` with FinalDate before IssueDate; `Plan Approval Expired`).
- After remapping Admin Closed/Voided out of Final, every remaining Final row has a usable FINAL_DATE.

After: 1,206 missing. Final coverage **100%** (793/793). Non-Final FINAL_DATE: **0**.  
Flags: **FILLED 250 · FIXED 201**.

## Repair script

`agent/scripts/fl/data_repair_fl_clay_county.py` — function `data_repair(df)`.

Artifact: `AGENT_DATA_PATH/clay_county_repaired_sample.parquet`.
