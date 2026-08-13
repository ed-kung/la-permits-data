# Key Biscayne (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Key Biscayne**. DATA is a uniform Accela Citizen Access payload (`status` / `date` / `tasks` / `search_data` / `inspections`). Upstream left 118 `STATUS_NORMALIZED` nulls (mostly unmapped `PRMT_EXP` / `P/R_EXP` / `Null/Void`, plus 40 blank-status shells) and mislabeled several rows from stale `STATUS_ORIGINAL` (e.g. Finaled kept as Active/In Review, Active kept as Inactive after prior rejection, Permit Ready kept as Active without issuance). `FILE_DATE` already matched `DATA.date` for all 2,000 rows. `PERMIT_DATE` matched Permit Issuance `Issue Permit` (or Revision/Shop Drawing `Issue Revision`) wherever both existed; most Final shells simply lack issuance events in DATA. `FINAL_DATE` matched Inspections `Final Inspection(s) Approved` for 1,243 rows and was fillable from passed Final* inspections on 83 more Final rows. The repair filled 78 statuses and fixed 28, filled 14 `PERMIT_DATE` values, filled 92 / fixed 1 `FINAL_DATE` values, and cleared spurious non-Final finals. After repair: STATUS 98.0% populated; FILE_DATE 100%; Active/Final PERMIT_DATE 84.9%/12.9%; Final FINAL_DATE 79.8%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Key Biscayne, FL** → `agent/scripts/fl/data_repair_fl_key_biscayne.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same Accela top-level keys (`address`, `date`, `details`, `more_details`, `record_type`, `search_data`, `status`, `tasks`, `inspections`, `contacts`, `fees_details`, etc.). Variants split by whether extras are non-empty and which canonical dates are recoverable:

| Schema | n | Notes |
| --- | ---: | --- |
| `accela_full_finaled` | 1,144 | Final date recoverable, no Issue event |
| `accela_full_applied` | 490 | Neither issued nor final |
| `accela_full_issued_finaled` | 191 | Issue + final |
| `accela_full_issued` | 99 | Issue event, no usable final |
| `accela_basic_applied` | 72 | Empty extras (no inspections/contacts/fees) |
| `accela_basic_finaled` | 3 | Basic shell with final signal |
| `accela_basic_issued` | 1 | Basic shell with Issue only |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status` (fallback `search_data.Status`); upgrade to Final when Final Inspection Approved / passed Final* inspection exists (except Inactive terminals); upgrade In Review → Active when Issue Permit/Revision exists |
| FILE_DATE | `search_data.Date` else `DATA.date` else Application Submittal Accepted/Applied |
| PERMIT_DATE | Earliest Permit Issuance `Issue Permit`, else Revision / Shop Drawing Issuance `Issue Revision` |
| FINAL_DATE | Latest Inspections `Final Inspection(s) Approved`, else latest passed Final* inspection |

## Field assessments

### STATUS_NORMALIZED

| DATA.status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Finaled | 1,520 | Final (1 Active, 1 In Review) | Fix → Final |
| Active | 77 | Active (5 Inactive); 4 with Final* insp → Final after repair | Fix Inactive → Active; Final-insp → Final |
| Final / CLOSED / Closed / CC Issued | 67 / 48 / 32 / 1 | Final (1 CLOSED as In Review) | Fix CLOSED → Final |
| PRMT_EXP / P/R_EXP | 40 / 18 | **null** | Fill → Inactive |
| Null/Void | 21 | **null** (18) / Inactive (2) / In Review (1) | → Inactive |
| Rejected / Void / Application Rejected / Canceled / Cancelled / Revoked / Expired | 24 / 24 / 9 / 9 / 2 / 3 / 4 | Inactive (1 Rejected as In Review; 1 Expired as Active) | Fix outliers → Inactive |
| On Review / Applied / Initiated / Ready / Resubmitted / Returned / Test | 21 / 4 / 4 / 1 / 1 / 1 / 1 | In Review | Correct |
| Permit Ready | 10 | Active | → In Review unless Issue event (1 upgraded to Active) |
| Issued | 16 | Active | Keep Active; 4 with passed Final* insp → Final |
| Resubmited / Checked-Out | 1 / 1 | **null** | Fill → In Review |
| (blank / None) | 40 | **null** | No status or task signal → leave null |

**Root causes:**
1. Upstream mapper omitted `PRMT_EXP`, `P/R_EXP`, most `Null/Void`, `Resubmited`, and `Checked-Out` → 78 fillable nulls (plus 40 blank shells).
2. `STATUS_ORIGINAL` sometimes disagreed with live `DATA.status` (e.g. Active rows still labeled `rejected`; Finaled labeled `active` / `on review`).
3. `Permit Ready` was labeled Active before issuance.
4. A few Issued / Active shells already carry passed Final* inspections and should be Final.

**Repair performance:** FILLED 78, FIXED 28; missing 118 → 40 (blank-status shells only).

### FILE_DATE

- Before: missing on **0 / 2,000**. Every value matches `DATA.date` at calendar-day resolution (1,992 also match `search_data.Date`; 8 lack search_data Date but keep `DATA.date`).
- Application Submittal Accepted/Applied is sparse (228 rows) and often differs from the Accela record date; the stored `FILE_DATE` correctly follows `DATA.date`.
- Ideal coverage after repair: 100% for every status class.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: missing on **1,723 / 2,000**. Present values matched Issue Permit / Issue Revision except none needing day-level correction (291/291 match after repair among rows with an Issue event).
- Filled 14 from Issue Permit on Active/Final/Inactive rows that previously lacked `PERMIT_DATE`.
- Cleared spurious `PERMIT_DATE` on In Review where present without a surviving Issue signal after status repair (included in status-driven transitions; no separate FIXED count beyond clears folded into status changes — In Review ends at 0/44 with PERMIT_DATE).
- Remaining Active/Final gaps (1,472): overwhelmingly older `Finaled` / `Closed` / `CLOSED` / `Issued` shells with no Issue Permit/Revision event in DATA (Finaled 1,390 of the gaps).

**Repair performance:** FILLED 14, FIXED 0; missing 1,723 → 1,709. Active coverage 84.9%; Final coverage 12.9%.

### FINAL_DATE

- Before: missing on **755 / 2,000**; among Final, missing 421. Present Final values matched Inspections `Final Inspection(s) Approved` for 1,242/1,244 comparable rows.
- Filled 92 Final `FINAL_DATE` values (task Final Inspection Approved after status upgrades, plus 83 from passed Final* inspections on shells lacking the task mark).
- Fixed 1 Final `FINAL_DATE` that equaled issuance (2020-11-03) while a later Final Building Approved inspection existed (2020-11-19).
- Cleared 1 spurious Active `FINAL_DATE` by upgrading that row to Final (kept the date) or clearing non-Final leftovers — after repair Active/In Review/Inactive all have 0 `FINAL_DATE`.
- Remaining Final gaps (339): `Finaled` (262), `CLOSED` (46), `Closed` (31) with neither Final Inspection Approved nor passed Final* inspections in DATA.

**Repair performance:** FILLED 92, FIXED 1; missing 755 → 663. Final coverage 79.8%.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_key_biscayne.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_fl_key_biscayne_repaired.parquet`
