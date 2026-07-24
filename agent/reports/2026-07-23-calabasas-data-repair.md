# Calabasas Permit Data Repair

Assessment and repair of STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for Calabasas records in `permits_la_sample.parquet` (2,000 records). The DATA column contains a consistent JSON schema with a `Build Status` string and a `My Project` dict holding date fields (`Submitted`, `Issued`, `Closed`, `Approved`, `Created`).

## Summary of Issues

| Field | Missing (before) | Incorrect | Filled | Fixed | Missing (after) |
|---|---|---|---|---|---|
| STATUS_NORMALIZED | 396 | 8 | 392 | 8 | 4 |
| FILE_DATE | 7 | 1 | 3 | 1 | 4 |
| PERMIT_DATE | 220 | 0 | 7 | 0 | 213 |
| FINAL_DATE | 670 | 0 | 6 | 0 | 664 |

## STATUS_NORMALIZED

### Missing values (396 → 4)

Two root causes:

1. **Build Status present in DATA but not propagated (96 records).** These have a `Build Status` field in the DATA JSON (e.g. "Expired: 3/11/2024", "Application Documents Accepted", "Issued") but STATUS_NORMALIZED was left null. All 26 expired-status records with NaN dates in 2023–2024 fall in this category, along with 43 application-stage records, 11 "Routed to Review", 9 "Required Submittal", and others. These are mapped using a direct lookup table.

2. **Build Status is None in DATA (300 records).** These are recently-scraped records where the source did not populate Build Status. Status was inferred from the `My Project` date fields:
   - Has `Closed` date → **Final** (110 records)
   - Has `Issued` date but no `Closed` → **Active** (132 records)
   - Has `Submitted` date but no `Issued`/`Closed` → **In Review** (54 records)
   - Empty `My Project` dict → cannot infer (4 records remain NaN)

### Incorrect values (8 records)

These are records where the permit status changed after the initial data load but STATUS_NORMALIZED was not updated:

| Change | Count | Explanation |
|---|---|---|
| Active → Final | 4 | Build Status updated to "Permit Finaled" with a `Closed` date |
| Active → Inactive | 3 | Build Status updated to "Expired: \<date\>" |
| In Review → Active | 1 | Build Status updated to "Issued" with an `Issued` date |

### Build Status → STATUS_NORMALIZED mapping

| Build Status | STATUS_NORMALIZED |
|---|---|
| Permit Finaled | Final |
| Issued, Reinstated Permit - Issued | Active |
| Expired: \<date\>, Plan Check Expired | Inactive |
| Planning Approved\*, Application Documents Accepted, Application is submitted (and variants), Permit Application Routed to Review, Required submittal items…, Ready (and variants), Returned to Applicant | In Review |

## FILE_DATE

Source field: `My Project.Submitted`.

- **3 filled:** Records with NaN FILE_DATE where `Submitted` was available in DATA (indices 10630, 11475, 11939).
- **1 fixed:** Index 11525 had FILE_DATE set to `Created` (2024-05-29) instead of `Submitted` (2024-07-08). The `Created` field represents when the record was created in the system, while `Submitted` is the formal application submission date.
- **4 remaining NaN:** Records with completely empty `My Project` dicts — no date information available.

## PERMIT_DATE

Source field: `My Project.Issued`.

- **7 filled:** Records whose status is Active or Final (after status repair) and had a `My Project.Issued` date available. This includes 1 record fixed from In Review → Active (idx 10419) and records whose status was filled from DATA.
- **213 remaining NaN:** 81 are Final records where `Issued` is "- -" (older permits where the issued date was not tracked), 77 are In Review (expected missing), and the rest are Inactive or records without Issued dates in DATA.

## FINAL_DATE

Source field: `My Project.Closed`.

- **6 filled:** Includes 4 records fixed from Active → Final that had `Closed` dates, plus 2 records whose status was filled as Final with available `Closed` dates.
- **664 remaining NaN:** 155 are Final records where `Closed` is "- -" (older permits without tracked close dates), and the remainder are Active, In Review, or Inactive (expected missing).

## STATUS_NORMALIZED distribution after repair

| Status | Before | After |
|---|---|---|
| Final | 1,369 | 1,485 |
| Active | 53 | 184 |
| In Review | 48 | 164 |
| Inactive | 134 | 163 |
| NaN | 396 | 4 |

## Artifacts

- Repair function: `agent/scripts/calabasas_data_repair.py`
  - Entry point: `data_repair(df)` — takes a DataFrame filtered to Calabasas, returns a copy with corrected fields and `{FIELD}_FLAG` columns.
