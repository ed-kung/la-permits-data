# Sumter County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Sumter County**. DATA is a uniform civic/eTRAKiT payload (`permit_info`, list-format `inspections`, etc.). `STATUS_NORMALIZED` was null for 10 rows (unmapped review labels + blank status with/without issuance) — 7 filled, 3 empty shells remain. Dates already matched `PermitAppliedDate` / `PermitIssuedDate` / `PermitFinaledDate` wherever those fields were set; repairs filled 1 `FILE_DATE`, 25 `PERMIT_DATE` (from `PermitApprovedDate`), and 4 `FINAL_DATE` (from passed FINAL/COFC inspections), and cleared 2 spurious Active `FINAL_DATE` values. After repair: STATUS 99.8% populated; FILE_DATE 99.8%; Active/Final PERMIT_DATE 100%/99.7%; Final FINAL_DATE 99.7%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Sumter County, FL** → `agent/scripts/fl/data_repair_fl_sumter_county.py` (1,999 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level keys: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Content variants split by which `permit_info` dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `civic_issued_finaled` | 1,748 | Issued + finaled dates |
| `civic_issued` | 142 | Issued, no finaled |
| `civic_applied` | 70 | Applied only |
| `civic_approved` | 28 | Approved (no issued/finaled) |
| `civic_finaled` | 8 | Finaled without issued |
| `civic_status_only` | 3 | Empty portal shells |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (blank + issued → Active) |
| FILE_DATE | `PermitAppliedDate` else `PermitIssuedDate` |
| PERMIT_DATE | `PermitIssuedDate` else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` else latest passed FINAL/COFC inspection |

## Field assessments

### STATUS_NORMALIZED

| PermitStatus (normalized) | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| FINALED / Finaled | 1,748 | Final | Correct |
| Issued / ISSUED | 83 | Active | Correct |
| CANCELLED / Cancelled | 84 | Inactive | Correct |
| EXPIRING | 23 | Inactive | Correct (issued, past/nearing expiry) |
| In Review / IN REVIEW | 19 | In Review | Correct |
| Closed Out / CLOSED OUT | 9 | Final | Correct |
| EXPIRED / Expired | 9 | Inactive | Correct |
| CO Issued / CO ISSUED | 7 | Final | Correct |
| REVIEW COMPLETE / Review Complete | 5 | In Review | Correct |
| (blank) | 6 | null (3); null→Active (3 with issued) | Fill when issued |
| HOLD - PLAN REV | 2 | **null** | Fill → In Review |
| EPERMIT APPLIED | 1 | **null** | Fill → In Review |
| PENDING ZONING | 1 | **null** | Fill → In Review |
| PENDING / AWAITING PAYMENT | 2 | In Review | Correct |

**Root cause of nulls:** upstream mapper did not cover `EPERMIT APPLIED`, `HOLD - PLAN REV`, or `PENDING ZONING`, and left blank-status issued shells unmapped. Three empty shells have no status or dates.

**Repair performance:** FILLED 7, FIXED 0; missing 10 → 3.

### FILE_DATE

- Before: missing on **4 / 1,999** rows. Present values always matched `PermitAppliedDate` at calendar-day resolution.
- Filled 1 row (blank applied, usable `PermitIssuedDate`).
- Remaining 3: empty shells with no date fields.

**Repair performance:** FILLED 1, FIXED 0; missing 4 → 3 (99.8% coverage). All Active/Final/In Review/Inactive rows with a real status have FILE_DATE.

### PERMIT_DATE

- Before: missing on **109 / 1,999**; present values always matched `PermitIssuedDate`.
- Filled 25 from `PermitApprovedDate` when issued was blank (6 Final, 19 Inactive).
- Remaining Active/Final gaps (5): FINALED/CLOSED OUT with neither issued nor approved.
- Remaining Inactive gaps: mostly never-issued cancels.

**Repair performance:** FILLED 25, FIXED 0; missing 109 → 84. Active coverage 100%; Final coverage 99.7%.

### FINAL_DATE

- Before: missing on **243 / 1,999**, including 10 Final rows; 2 Active (`ISSUED`) rows incorrectly carried `PermitFinaledDate` (= issued day).
- Filled 4 Final gaps from passed FINAL/COFC list-format inspections when `PermitFinaledDate` was blank.
- Cleared 2 spurious Active finals (FIXED).
- Remaining Final gaps (6): CLOSED OUT / FINALED with no finaled stamp and no usable final inspection.

**Repair performance:** FILLED 4, FIXED 2; missing 243 → 241. Final coverage: 99.7% (1,758 / 1,764).

## Ideal-field checklist (after repair)

| Rule | Result |
| --- | --- |
| FILE_DATE populated for all records | Mostly (99.8%; 3 empty shells) |
| PERMIT_DATE for Active and Final | Near-complete (100% / 99.7%) |
| FINAL_DATE for Final | Near-complete (99.7%; 6 lack final stamp/inspection) |

Status distribution after repair: Final 1,764; Inactive 116; Active 86; In Review 30; null 3.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_sumter_county.py`
- Repaired sample: `$AGENT_DATA_PATH/sumter_county_repaired_sample.parquet`
