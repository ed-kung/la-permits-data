# Fort Pierce (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-appearance order) was **Fort Pierce**. DATA is the Tamarac/Ormond Beach-style city portal payload (`detail`, `fees`, optional `permit_status_detail` / `insp_status_detail`). Upstream left 58 `STATUS_NORMALIZED` nulls on fees-only shells, mislabeled one CLOSED row as Active via stale `STATUS_ORIGINAL=permit printed`, and kept 52 VOID/REJECTED applications as Final. `FILE_DATE` already matched Application Date for every row. `PERMIT_DATE` was copied from portal **Permit Date**, which on Final rows is usually a close/admin stamp after **Issue Date** — 1,441 rows were corrected to Issue Date and 119 spurious Permit-Date stamps (In Review / no Issue Date) were cleared. `FINAL_DATE` was filled/fixed from successful Final/CO inspections and/or Permit Date when strictly after Issue Date. After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 100%/98.9%; Final FINAL_DATE 99.3%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Fort Pierce, FL** → `agent/scripts/fl/data_repair_fl_fort_pierce.py` (1,999 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `permit_status_closed` | 1437 | Full permit + inspection blocks |
| `permit_status_permit_printed` | 384 | Issued / active |
| `permit_status_plan_check` | 54 | Pre-issuance |
| `permit_status_final_inspection_complete` | 35 | Final |
| `fees_detail_in_plan_check` | 29 | No permit/insp blocks |
| `permit_status_permit_revoked` | 24 | Inactive |
| `fees_detail_void` | 16 | No permit/insp blocks |
| `fees_detail_closed` | 10 | No permit/insp blocks |
| `permit_status_c_o_issued` | 4 | Final |
| `fees_detail_approved` | 3 | No permit/insp blocks |
| `permit_status_to_be_issued` | 3 | Pre-issuance |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_status_detail["Status for Permit Number"]`; terminal Application Status (VOID/REJECTED/…) overrides to Inactive; fees_detail uses `detail["Application Status"]` |
| FILE_DATE | `Application Date` (detail or permit_status_detail) |
| PERMIT_DATE | `Issue Date` (not portal `Permit Date`) |
| FINAL_DATE | Later of successful Final/CO (else latest non-NOC success) inspection date and portal `Permit Date` when strictly after Issue Date |

## Field assessments

### STATUS_NORMALIZED

Upstream mapped almost entirely from `Status for Permit Number` / `STATUS_ORIGINAL`:

| Status for Permit Number | Upstream STATUS_NORMALIZED | Assessment |
| --- | --- | --- |
| CLOSED | Final (1 Active) | Fix Active → Final |
| PERMIT PRINTED | Active | Correct |
| PLAN CHECK | In Review | Correct |
| FINAL INSPECTION COMPLETE | Final | Correct |
| PERMIT REVOKED | Inactive | Correct |
| C.O. ISSUED | Final | Correct |
| TO BE ISSUED | In Review | Correct |
| *(missing — fees_detail)* | **null** (58) | Fill from Application Status |

**Root causes:**
1. Fees-only shells lack `permit_status_detail`, so upstream left status null despite `Application Status` (VOID → Inactive, IN PLAN CHECK/APPROVED → In Review, CLOSED → Final).
2. One CLOSED row retained stale `STATUS_ORIGINAL=permit printed` / `STATUS_NORMALIZED=Active`.
3. Application Status VOID (51) / REJECTED (1) on otherwise CLOSED/Final permit shells should be Inactive (same override as sibling portal cities).

**Repair performance:** FILLED 58, FIXED 53; missing 58 → 0.

### FILE_DATE

- Before: missing on **0 / 1,999**. All values matched `Application Date` at calendar-day resolution.
- No fills or fixes needed.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: NaN on **58 / 1,999** (exactly the fees_detail shells). Present values matched portal **Permit Date**, not **Issue Date**.
- On PERMIT PRINTED rows Issue ≈ Permit Date (380 equal / 5 differ). On CLOSED / FINAL INSPECTION COMPLETE / C.O. ISSUED, Issue and Permit Date differ for nearly all rows (Permit Date is later — close/admin stamp).
- Ideal PERMIT_DATE is issuance → **Issue Date**. In Review rows must not carry PERMIT_DATE.

**Repair performance:** FILLED 0, FIXED 1,560 (1,441 rewritten to Issue Date; 119 cleared). Missing 58 → 177. Active 100%; Final 98.9% (16 shells lack Issue Date: 10 fees_detail_closed + 6 permit_status_closed); In Review 0%.

### FINAL_DATE

- Before: NaN on **802 / 1,999**; Final coverage 1,197 / 1,475 (81.2%). Many present values used an early non-final inspection rather than the latest Final/CO success; many Finals lacked FINAL_DATE despite a post-Issue Permit Date close stamp.
- Repair uses max(successful Final/CO insp or latest non-NOC success, Permit Date if strictly after Issue Date).

**Repair performance:** FILLED 227, FIXED 1,174; missing 802 → 575. Final coverage 1,424 / 1,434 (99.3%). Remaining 10 gaps are fees_detail_closed shells with no Issue/Permit/inspection dates. Non-Final rows correctly have 0% FINAL_DATE. PERMIT_DATE > FINAL_DATE inversions: 0.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_fort_pierce.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_fort_pierce_repaired.parquet`
