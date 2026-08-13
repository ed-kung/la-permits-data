# Royal Palm Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-appearance order) was **Royal Palm Beach**. DATA is the Fort Pierce / Tamarac-style city portal payload (`detail`, `fees`, optional `permit_status_detail` / `insp_status_detail`). Upstream left 16 `STATUS_NORMALIZED` nulls on fees-only shells, kept 23 Finals mislabeled as In Review/Active via stale `STATUS_ORIGINAL`, and kept 9 VOID applications as Active/Final/In Review. `FILE_DATE` already matched Application Date for every row. `PERMIT_DATE` was copied from portal **Permit Date**, which on Final rows is usually a close/admin stamp after **Issue Date** — 1,671 rows were corrected to Issue Date and 76 spurious stamps (In Review / no Issue Date) were cleared. `FINAL_DATE` was filled/fixed from successful Final/CO inspections and/or Permit Date when strictly after Issue Date. After repair: STATUS 99.95% (1 blank fees shell); FILE_DATE 100%; Active/Final PERMIT_DATE 100%/99.0%; Final FINAL_DATE 99.6%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Royal Palm Beach, FL** → `agent/scripts/fl/data_repair_fl_royal_palm_beach.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `permit_status_final_inspection_complete` | 784 | Full permit + inspection blocks |
| `permit_status_closed` | 722 | Full permit + inspection blocks |
| `permit_status_permit_printed` | 239 | Issued / active |
| `permit_status_c_o_issued` | 169 | Final |
| `permit_status_plan_check` | 51 | Pre-issuance |
| `permit_status_permit_revoked` | 17 | Inactive |
| `fees_detail_in_plan_check` | 7 | No permit/insp blocks |
| `fees_detail_closed` | 6 | No permit/insp blocks |
| `permit_status_to_be_issued` | 2 | Pre-issuance |
| `fees_detail_none` | 1 | Blank Application Status |
| `fees_detail_approved` | 1 | No permit/insp blocks |
| `fees_detail_void` | 1 | No permit/insp blocks |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_status_detail["Status for Permit Number"]`; terminal Application Status (VOID/…) overrides to Inactive; fees_detail uses `detail["Application Status"]` |
| FILE_DATE | `Application Date` (detail or permit_status_detail) |
| PERMIT_DATE | `Issue Date` (not portal `Permit Date`) |
| FINAL_DATE | Later of successful Final/CO (else latest non-NOC success) inspection date and portal `Permit Date` when strictly after Issue Date |

## Field assessments

### STATUS_NORMALIZED

Upstream mapped almost entirely from `Status for Permit Number` / `STATUS_ORIGINAL`, but stale originals caused mismatches:

| Status for Permit Number | Upstream STATUS_NORMALIZED | Assessment |
| --- | --- | --- |
| FINAL INSPECTION COMPLETE | Final (761), In Review (14), Active (9) | Fix stale In Review/Active → Final |
| CLOSED | Final | Correct (except VOID override) |
| PERMIT PRINTED | Active (230), In Review (8), Inactive (1) | Fix stale In Review/Inactive → Active |
| C.O. ISSUED | Final | Correct |
| PLAN CHECK | In Review | Correct (except VOID override) |
| PERMIT REVOKED | Inactive | Correct |
| TO BE ISSUED | In Review | Correct |
| *(missing — fees_detail)* | **null** (16) | Fill from Application Status when mappable |

**Root causes:**
1. Fees-only shells lack `permit_status_detail`, so upstream left status null despite `Application Status` (CLOSED → Final, IN PLAN CHECK/APPROVED → In Review, VOID → Inactive). One blank Application Status row remains null.
2. Stale `STATUS_ORIGINAL` (`plan check` / `permit printed` / `permit revoked`) disagreed with current `Status for Permit Number` on 32 rows.
3. Application Status VOID (9) on otherwise Final/Active/In Review shells should be Inactive.

**Repair performance:** FILLED 15, FIXED 41; missing 16 → 1.

### FILE_DATE

- Before: missing on **0 / 2,000**. All values matched `Application Date` at calendar-day resolution.
- No fills or fixes needed.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: NaN on **16 / 2,000** (exactly the fees_detail shells). Present values matched portal **Permit Date**, not **Issue Date** (1,951 equal Permit Date vs 237 equal Issue Date; 1,670 Issue≠Permit Date pairs, nearly all Final with Permit Date later).
- Ideal PERMIT_DATE is issuance → **Issue Date**. In Review rows must not carry PERMIT_DATE (all 75 In Review rows had a spurious stamp).
- 835 PERMIT_DATE > FINAL_DATE inversions before repair were an artifact of using close stamps as issuance.

**Repair performance:** FILLED 0, FIXED 1,747 (1,671 rewritten to Issue Date; 76 cleared). Missing 16 → 92. Active 100%; Final 99.0% (17 lack Issue Date: 11 `permit_status_closed` + 6 `fees_detail_closed`); In Review 0%. PERMIT_DATE > FINAL_DATE inversions after: 0.

### FINAL_DATE

- Before: NaN on **449 / 2,000**; Final coverage 1,551 / 1,652 (93.9%). Most present values matched inspection success dates; 100 Finals had a usable candidate (insp and/or post-Issue Permit Date) but missing FINAL_DATE; 6 mismatched the preferred candidate.
- Repair uses max(successful Final/CO insp or latest non-NOC success, Permit Date if strictly after Issue Date).

**Repair performance:** FILLED 119, FIXED 835; missing 449 → 330. Final coverage 1,670 / 1,677 (99.6%). Remaining 7 gaps: 6 `fees_detail_closed` shells with no dates/inspections, plus 1 `permit_status_closed` with Issue Date = Permit Date and empty inspections (no post-issue close stamp). Non-Final rows correctly have 0% FINAL_DATE.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_royal_palm_beach.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_royal_palm_beach_repaired.parquet`
