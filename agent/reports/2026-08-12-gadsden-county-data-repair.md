# Gadsden County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Gadsden County**. DATA is a city-portal payload (`Applications` / `Fees and Payments` / `Permit Information` / `Inspections History` / `Permit Requirements` / `Plan Review History`; Pascal key casing). Upstream `STATUS_NORMALIZED` already matched `Permit Information.StatusDesc` for every row, and `FILE_DATE` already matched earliest `Applications.AppDate`. `PERMIT_DATE` was a same-day copy of `FILE_DATE` on all 248 rows — `ApprovedByDate` exists on only 1 shell — so issuance was repaired from earliest fee `DatePaid` when present (129 FIXED). `FINAL_DATE` was missing on every row; Final coverage rose to 98.6% (139 / 141) from Passed `*Final*` inspections plus a last-Passed fallback for close-outs not named FINAL. After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 100% populated (144 / 145 backed by fee/approval evidence); Final FINAL_DATE 98.6%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Gadsden County, FL** → `agent/scripts/fl/data_repair_fl_gadsden_county.py` (248 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level key set. Content suffixes split by which canonical dates are recoverable (`ApprovedByDate` / fee `DatePaid` for issued; Passed FINAL-named inspection for finaled):

| Schema | n | Notes |
| --- | ---: | --- |
| `city_portal_issued_finaled` | 137 | Fee/approval + Passed FINAL inspection |
| `city_portal_issued` | 104 | Fee/approval, no FINAL-named inspection |
| `city_portal_applied` | 6 | Neither issuance nor FINAL inspection |
| `city_portal_finaled` | 1 | FINAL inspection without fee/approval date |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Permit Information[0].StatusDesc` |
| FILE_DATE | Earliest `Applications[].AppDate` |
| PERMIT_DATE | Earliest `Applications[].ApprovedByDate`, else earliest `Fees and Payments[].DatePaid` |
| FINAL_DATE | Latest Passed inspection with `FINAL` in `inspectiondesc`; for Final only, else latest Passed inspection of any type |

## Field assessments

### STATUS_NORMALIZED

| StatusDesc | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Permit Complete | 141 | Final | Correct |
| Expired | 97 | Inactive | Correct |
| Voided | 5 | Inactive | Correct |
| Permit Issued | 4 | Active | Correct |
| Canceled Permit | 1 | Inactive | Correct |

No nulls. Upstream mapping already matched `StatusDesc` 1:1; no In Review values in this sample.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0.

### FILE_DATE

- Before: missing on **0 / 248**. Every value matches earliest `Applications.AppDate` at calendar-day resolution (also matches primary `AppDate` on 242 / 248; 6 multi-app shells correctly keep the earlier subordinate filing date).
- Ideal coverage already 100% for every status class.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: present on all 248 rows, but **every value equals `FILE_DATE`**. `ApprovedByDate` is non-null on only 1 voided shell (same calendar day as `AppDate`). Root cause: upstream copied the application date into `PERMIT_DATE` rather than an issuance signal.
- Fees provide a usable issuance proxy: 240 / 248 shells have `DatePaid`; earliest paid date is on or after `FILE_DATE` and never creates a PERMIT > FINAL inversion against Passed FINAL inspections.
- Repair overwrites from `ApprovedByDate` else earliest `DatePaid` when that differs from the FILE_DATE copy → **129 FIXED** (74 Final, 52 Inactive, 3 Active).
- After repair, Active/Final stay fully populated (145 / 145). 144 / 145 have fee or approval evidence; **1 Active** shell (`2114947-1`, Permit Issued) has empty fees and null `ApprovedByDate`, so the FILE_DATE copy is left as-is. 67 other Active/Final rows still show PERMIT_DATE == FILE_DATE because fees were paid the same calendar day (plausible same-day issuance; not flagged).

**Repair performance:** FILLED 0, FIXED 129; missing 0 → 0. Active 100%; Final 100%.

### FINAL_DATE

- Before: NaN on **248 / 248** (including all 141 Final rows).
- Primary fill: latest Passed inspection whose description contains `FINAL` → 130 Final rows. `Passed Partial` / `Failed` / `Canceled Inspection` are ignored.
- Fallback for Final shells whose close-out is not named FINAL (e.g. MH Code Compliance, Structural Roof coverings, Electric Service Release) → latest Passed inspection of any type → **+9 FILLED**.
- Remaining gaps (2 Final): `2114783-0` (only Failed Mechanical Final) and `2114720-0` (only Passed Partial Electrical Final) — no Passed close-out date in DATA.
- Non-Final rows correctly keep `FINAL_DATE` null (Active shells with Passed FINAL inspections are not finaled).

**Repair performance:** FILLED 139, FIXED 0. Final coverage 98.6% (139 / 141). Active / Inactive FINAL_DATE 0%. PERMIT_DATE > FINAL_DATE inversions after repair: 0.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_gadsden_county.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_gadsden_county_repaired.parquet`
