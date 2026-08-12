# Palm Coast (FL) data repair

**Summary:** Palm Coast (`2,001` sample rows) uses an eTRAKiT-style DATA payload. `STATUS_NORMALIZED` was already correct for mapped portal statuses; 10 unmapped rows (`ADMCLSD` / `CODEACT` / `STATE`) were filled. `FILE_DATE` was 100% missing and is now filled for 1,928 rows from review / fee / issue dates. `PERMIT_DATE` already matched `Issue Date` with no Active/Final gaps. The main defect was `FINAL_DATE`: upstream copied `Expiration Date` (~Issue+6 months) rather than completion; the repair replaces it with approved FINAL inspection dates for Final rows and clears spurious Expiration stamps elsewhere.

## Jurisdiction selection

First `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Palm Coast, FL**.

Script: `agent/scripts/fl/data_repair_fl_palm_coast.py`  
Artifact: `$AGENT_DATA_PATH/palm_coast_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

Two layout variants, further split by which date/history signals are present:

| Schema family | n | Notes |
| --- | ---: | --- |
| `etrakit_flat_*` | 1,724 | Flattened `owner_*` / `Applicant Name` / `Name`; usually has `Expiration Date` |
| `etrakit_nested_*` | 277 | Nested `Owner` / `Contractor` / `Sub Contractors`; no `Expiration Date` |

Content suffixes: `_issued_insp_rev` (906+88), `_issued_insp` (575+89), `_issued_rev`, `_issued`, `_insp_rev`, `_rev`, `_status_only` (73 thin cancel/ready shells).

Canonical fields: `Status`, `Issue Date`, `Expiration Date`, `Fees[].Date Paid`, `Review History[].Date In`, `Inspection History[].{Type,Result,Request Date}`.

## Field assessments

### STATUS_NORMALIZED

| Portal `Status` | Prior mapping | Assessment |
| --- | --- | --- |
| FINAL, COED | Final | Correct |
| ISSUED, INSPECT | Active | Correct |
| APPLY, READY | In Review | Correct |
| CANCEL, EXPIRED, VOID | Inactive | Correct |
| ADMCLSD (7) | null | Filled → Final (admin closed) |
| CODEACT (2) | null | Filled → Active |
| STATE (1) | null | Filled → Active |

No incorrect non-null statuses found (`STATUS_ORIGINAL` == `DATA.Status` for all rows).

**Repair performance:** FILLED 10, FIXED 0; missing 10 → 0.

### FILE_DATE

- Before: missing on **all 2,001** rows.
- Source: earliest `Review History.Date In` (best application/review start; present on ~1,167), else earliest `Fees.Date Paid` (~1,750 but usually equals Issue), else `Issue Date`.
- After: missing **73** (cancel/void/ready `status_only` shells with no review, fee, or issue dates).
- Active/Final coverage after repair: **100%**.

**Repair performance:** FILLED 1,928, FIXED 0; missing 2,001 → 73.

### PERMIT_DATE

- When present, matched `Issue Date` on **1,840 / 1,840** (100%).
- Active/Final already fully populated; remaining missings are In Review (39) and never-issued Inactive (122) — appropriate.
- No fills or fixes required.

**Repair performance:** FILLED 0, FIXED 0; missing 161 → 161.

### FINAL_DATE

- Before: 1,612 of 1,612 non-null values equaled `Expiration Date` (median Issue→Expiration gap ≈ 180–205 days) — **not** a finalization date.
- Nested rows lacked Expiration, so Final nested rows were often missing `FINAL_DATE` entirely.
- True completion signal: latest inspection with Result `FINAL APPROVED`, or Type containing `FINAL` with an approved (non-disapproved) result (`Request Date`).
- Inactive cancel/expired/void rows incorrectly carried Expiration as `FINAL_DATE` → cleared.

**Repair performance:** FILLED 203, FIXED 1,612 (1,365 replaced with inspection dates; 247 cleared). Missing 389 → 433 (net rise from clearing bad Expiration values without a replacement inspection).

After repair by status:

| Status | FINAL_DATE present |
| --- | --- |
| Final | 1,568 / 1,632 (96.1%) |
| Active / In Review / Inactive | 0% (as expected) |

Remaining 64 Final rows without `FINAL_DATE` have no approved FINAL inspection in DATA (mostly `final`/`admclsd` issued shells). Zero repaired `FINAL_DATE` values still equal Expiration Date.

## Ideal-field checklist (after repair)

| Rule | Result |
| --- | --- |
| FILE_DATE ideally for all | 1,928 / 2,001 (96.4%); gaps only on empty cancel/ready shells |
| PERMIT_DATE for Active & Final | 100% |
| FINAL_DATE for Final | 96.1% |
