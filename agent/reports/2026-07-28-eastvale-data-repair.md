# Eastvale (CA) data repair

Eastvale was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` supports filling all 104 blank statuses as In Review, correcting 10 In Review→Active lags where Permit Issuance was already Issued, and filling 3 missing `FINAL_DATE` values on `Finaled` shells from Passed Final inspections. `FILE_DATE` was already complete and correct. One Active `Issued` row still lacks a dated Permit Issuance event, so `PERMIT_DATE` remains missing there. Passed Final inspections on still-Issued shells are not treated as Final (agency status lag).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: Eastvale, CA (1,093 sample rows)
- Script: `agent/scripts/ca/data_repair_ca_eastvale.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_eastvale_repaired.parquet`

## DATA schema

Two top-level key-set variants appear:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `portal_issued` | 449 | Permit Issuance Issued; no final-inspection date |
| `portal_issued_finaled` | 444 | Issued + Final Inspection Complete and/or Passed Final inspection |
| `portal_application_only` | 178 | Top-level / Application Submittal date only (includes blank-status shells) |
| `search_data_only` | 20 | Only `search_data` (Date present; Status blank) |
| `portal_final_insp_only` | 2 | Passed Final inspection without Issued event |

Canonical Accela fields:

| DATA source | Target field |
| --- | --- |
| `status` / `search_data.Status` (+ Issued upgrade) | `STATUS_NORMALIZED` |
| Earliest of `date` / `search_data.Date` / Application Submittal Accepted* | `FILE_DATE` |
| Earliest Permit Issuance `Issued` | `PERMIT_DATE` |
| Earliest Inspection `Final Inspection Complete` (fallback: Passed Final inspection `Status Date`) | `FINAL_DATE` |

## Findings by field

### STATUS_NORMALIZED

- Before: Active 554, Final 325, In Review 105, Inactive 5, null 104.
- Nulls are blank `DATA.status` / `STATUS_ORIGINAL` (84 TBD-only Application Submittal shells + 20 `search_data`-only). Filled as **In Review**.
- Upstream mapping of present Accela labels (`Issued` / `Permit Issued` / `Issued - Documents Required` → Active; `Closed - Complete` / `Finaled` → Final; `Expired` → Inactive; review-stage labels → In Review) was already correct.
- **FIXED** 10 In Review rows that already had a dated Permit Issuance `Issued` event (Ready to Issue, Plan Review, Pending, Resubmittal Required) → Active.
- Did **not** promote Issued / Permit Issued rows with Passed Final inspections to Final while portal status remains Issued (118 Active rows).

### FILE_DATE

- Already populated on 1,093 / 1,093 rows.
- Matches `DATA.date` / `search_data.Date` in every comparable row; Application Submittal Accepted dates are never earlier.
- No FILLED / FIXED changes.

### PERMIT_DATE

- Missing 200 / 1,093 before and after. After repair, coverage is Active 563/564 (99.8%), Final 325/325 (100%), In Review 0/199, Inactive 5/5.
- When present and an Issued event exists, values match the earliest Permit Issuance `Issued` mark (0 incorrect among comparable rows).
- The 10 In Review→Active promotions already carried `PERMIT_DATE`.
- One Active `Issued` row has no Permit Issuance task history → unfillable.

### FINAL_DATE

- Missing 771 before → 768 after.
- After repair: Final 325/325 (100%); Active / In Review / Inactive have none.
- Filled 3 `Finaled` rows from Passed Final inspection `Status Date` (Inspection task lacked `Final Inspection Complete`).
- Remaining Closed - Complete finals already matched Inspection `Final Inspection Complete` (and usually the same Passed Final inspection date).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 104 | 10 | 104 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 200 → 200 |
| FINAL_DATE | 3 | 0 | 771 → 768 |

Status after repair: Active 564, Final 325, In Review 199, Inactive 5.

Chronology after repair: 0 `PERMIT_DATE` < `FILE_DATE`; 0 `FINAL_DATE` < `PERMIT_DATE`.
