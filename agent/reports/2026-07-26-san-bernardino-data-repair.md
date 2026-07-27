# San Bernardino (CA) data repair

**Summary:** San Bernardino was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the city permit-portal `DATA` JSON. Status is now fully populated (**FILLED 132 · FIXED 14**): unmapped CODE/LIEN/ZV statuses were filled, and 14 rows where `STATUS_ORIGINAL` disagreed with `permit_status` were corrected. `FILE_DATE` already matched `DATA['File Date']` for all 2,001 rows (no changes). `PERMIT_DATE` was missing on every row; for Active/Final it is now complete (**FILLED 1,508**) via Status ISSUED/JOB CARD notes, `AP:Approved` dates, earliest inspection, payment, or File Date as OTC proxy. `FINAL_DATE` missingness on Final rows fell such that **695 / 747 (93.0%)** now have a finaling / close-out date (**FILLED 695**). Remaining Final gaps are mostly CODE shells without a close inspection and a handful of FINAL/COMPLETE/RECORDED rows with no usable final inspection.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **San Bernardino, CA** (n=2,001)
- Script: `agent/scripts/ca/data_repair_ca_san_bernardino.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records share the same top-level keys (`permit_status`, `File Date`, `Status`, `Payments`, `Completed Inspections`, `Scheduled Inspections`, `Fees`, `Type / Classification`, …). Sub-schemas reflect which date sources are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_inspections` | 790 | Completed inspections; empty `Status` |
| `portal_payments_only` | 497 | Payments only; no Status / inspections |
| `portal_shell` | 384 | File Date only |
| `portal_status_and_inspections` | 219 | Dated Status events + inspections |
| `portal_status_events` | 111 | Dated Status events; no inspections |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.permit_status` |
| `FILE_DATE` | `DATA['File Date']` |
| `PERMIT_DATE` | Status ISSUED/JOB CARD comment date → `AP:Approved` Status Date → earliest Completed Inspection → earliest non-void Payment → File Date |
| `FINAL_DATE` | Latest approved `BUILDING FINAL` / `FINAL*` inspection (incl. legacy null-status BUILDING FINAL); `Approved: Finaled`; `STAT CLOSE COMPLAINT`; Fire Inspection with FINAL comment |

## Field assessment

### STATUS_NORMALIZED

**Before:** Active 730 · Final 683 · Inactive 245 · In Review 211 · missing 132

Upstream normalization used `STATUS_ORIGINAL` (lowercased `permit_status`) and only mapped common building-permit codes. Two failure modes:

1. **132 null statuses** — CODE / LIEN / planning codes never mapped (`VOLUNTRY` 42, `SUBMITTD` 12, `PICKEDUP` 12, `UNFOUND` 11, `REQ INSP` 10, plus NOTICE1, HEARING, ADCLOSED, …).
2. **14 mismatches** where `STATUS_ORIGINAL` ≠ current `permit_status` (stale original):
   - `issued` / Active while `permit_status=FINAL` (11) → Final (many already have approved BUILDING FINAL)
   - `plan ck` / In Review while `permit_status=ISSUED` (2) → Active
   - `issued` / Active while `permit_status=EXPIRED` (1) → Inactive

`permit_status` → normalized mapping used:

| `permit_status` | `STATUS_NORMALIZED` |
| --- | --- |
| FINAL, COMPLETE, CLOSED, RECORDED, ADCLOSED, RESOLUTN, VOLUNTRY, CORRECTD | Final |
| ISSUED, APPROVED, PICKEDUP, REQ INSP, EXTENSIO, ORDER, CITATION, 24 HOUR, 72 HOUR, NOTICE1 | Active |
| APPLIED, PAID, PLAN CK, PLANCK, SUBMITTD, RECEIVED, COURTESY, PC, Pend-MCC, HEARING, REFERRED, SUSPEND | In Review |
| EXPIRED, VOID, CANCEL, WITHDRWN, DENIED, INVALID, ABANDOND, DUPLCATE, UNFOUND | Inactive |

**After:** Active 761 · Final 747 · Inactive 260 · In Review 233 · missing 0  
Flags: **FILLED 132 · FIXED 14**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA['File Date']` at calendar-day resolution.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 2,001 missing (100%), including all Active/Final rows.

Root cause: DATA has **no dedicated issued-date field**. Issuance is only recoverable from Status workflow notes, approval marks, inspections (implies a live permit), payments, or File Date for OTC-style records.

Fill hierarchy for Active/Final (source counts among 1,508 FILLED):

| Source | n |
| --- | ---: |
| Earliest completed inspection | 733 |
| Earliest non-void payment | 339 |
| File Date (last-resort OTC proxy) | 244 |
| Status comment ISSUED / JOB CARD | 123 |
| Status `AP:Approved` date | 69 |

**After:** missing 493 (only In Review / Inactive, by design). Active/Final: **1,508 / 1,508 (100%)**.  
Flags: **FILLED 1,508 · FIXED 0**

Note: payment and File Date proxies are weak when no Status/inspection signal exists (~583 rows); they often share the application calendar day for OTC permits.

### FINAL_DATE

**Before:** 2,001 missing (100%), including all 683 Final rows.

Repairs for Final status only, from Completed Inspections:

- Approved (or legacy null-status) `BUILDING FINAL`
- Other approved inspections with `FINAL` in the description
- `Approved: Finaled`
- Code close-outs: `STAT CLOSE COMPLAINT or FILE`
- Fire Inspection with FINAL in the inspector comment

**After:** Final **695 / 747 (93.0%)** populated. Remaining 52 Final without a usable close/final inspection:

| `permit_status` | n |
| --- | ---: |
| VOLUNTRY | 20 |
| FINAL | 11 |
| COMPLETE | 8 |
| ADCLOSED | 6 |
| RECORDED | 3 |
| CORRECTD | 2 |
| CLOSED | 1 |
| RESOLUTN | 1 |

Flags: **FILLED 695 · FIXED 0**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 132 | 14 | 132 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 1,508 | 0 | 2,001 → 493 |
| `FINAL_DATE` | 695 | 0 | 2,001 → 1,306 |

Post-repair coverage vs ideals:

- `FILE_DATE` populated: **100%**
- `PERMIT_DATE` on Active/Final: **100%**
- `FINAL_DATE` on Final: **93.0%**

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_san_bernardino.py`
- This report: `agent/reports/2026-07-26-san-bernardino-data-repair.md`
