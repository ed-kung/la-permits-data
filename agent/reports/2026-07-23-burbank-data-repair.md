# Burbank Data Repair Assessment

Assessment and repair of STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for Burbank permit records (2,001 records in `permits_la_sample.parquet`), using the raw DATA JSON column as ground truth.

## Summary

The Burbank DATA column uses a flat, consistent "custom" schema with the keys `Permit Status`, `Applied Date`, `Issue Date`, and `Completed` mapping directly to STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE respectively. Date values, when present in both the normalised field and DATA, are consistent with zero mismatches. The main issues are **incorrect STATUS_NORMALIZED mappings** for 148 records, plus 1 fillable FINAL_DATE.

## Findings

### STATUS_NORMALIZED (148 repairs: 2 FILLED, 146 FIXED)

The STATUS_NORMALIZED field was derived from STATUS_ORIGINAL, which almost always matches the DATA column's `Permit Status` (only 3 out of 2,001 records differ). Four categories of errors were found:

| Raw Permit Status | Current STATUS_NORMALIZED | Correct STATUS_NORMALIZED | Count | Reason |
|---|---|---|---|---|
| Admin Completed | In Review | **Final** | 123 | Status says "Completed"; all 123 records have a Completed date in DATA |
| Archived | In Review | **Inactive** | 21 | Terminal state with no further activity; no Completed dates |
| Department Clearance | NaN | **In Review** | 2 | STATUS_ORIGINAL = "department clearance" was not mapped |
| Department Clearance | Active | **In Review** | 1 | STATUS_ORIGINAL = "permit issued" diverges from DATA's actual Permit Status |
| Final (DATA) | Active | **Final** | 1 | STATUS_ORIGINAL = "issued" diverges from DATA's actual Permit Status; record has both Issue Date and Completed |

The 3 records where STATUS_ORIGINAL diverges from the DATA column's Permit Status suggest the source data was updated after the initial ingest pipeline captured the original status.

### FILE_DATE (0 repairs)

10 records are missing FILE_DATE. In all 10 cases, the DATA column's `Applied Date` is also empty, so no fills are possible from DATA. The remaining 1,991 records have FILE_DATE correctly populated and consistent with `Applied Date`.

### PERMIT_DATE (113 repairs: 113 FILLED)

888 records are missing PERMIT_DATE. For all records where PERMIT_DATE is missing, the DATA column's `Issue Date` is also empty — no fills are possible from `Issue Date` alone. Where both exist (1,112 records), the values are consistent with zero mismatches.

For **Building Administration** (74 fills) and **Code Enforcement** (39 fills) permit types, filing and issuance are the same event: when both FILE_DATE and PERMIT_DATE are populated, they are always equal (100% match rate, 5/5 and 1/1 respectively). For Active/Final records of these types with missing PERMIT_DATE, the repair fills PERMIT_DATE = FILE_DATE. This brings "Final" PERMIT_DATE coverage from 75.4% to 99.6%.

### FINAL_DATE (1 repair: 1 FILLED)

1 record has FINAL_DATE missing but `Completed` present in DATA. This is the STATUS_ORIGINAL/Permit Status mismatch record (STATUS_ORIGINAL = "issued", DATA Permit Status = "Final") which was categorised as "Active" and therefore didn't receive a FINAL_DATE during initial processing. After fixing the status to "Final", FINAL_DATE is filled from Completed = "07/26/2024".

The remaining 1 missing FINAL_DATE among "Final" records is a "Closed" permit with no Completed date in DATA.

## Post-repair quality

| Field | Status group | Coverage |
|---|---|---|
| STATUS_NORMALIZED | all | 2,001 / 2,001 (100%) |
| FILE_DATE | all | 1,991 / 2,001 (99.5%) |
| PERMIT_DATE | Active + Final | 629 / 688 (91.4%) |
| FINAL_DATE | Final | 459 / 460 (99.8%) |

## Artifacts

- **Repair script**: `agent/scripts/burbank_data_repair.py`
  - Function `data_repair(df)` takes a Burbank-filtered DataFrame, returns a copy with corrected values and `{FIELD}_FLAG` columns ("FILLED" or "FIXED").
  - Includes a CLI entrypoint that prints repair statistics when run standalone.
