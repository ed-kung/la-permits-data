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

### PERMIT_DATE (0 repairs)

888 records are missing PERMIT_DATE. For all records where PERMIT_DATE is missing, the DATA column's `Issue Date` is also empty — no fills are possible from DATA. Where both exist (1,112 records), the values are consistent with zero mismatches. After the STATUS_NORMALIZED fix, 113 records in the "Final" group (mostly former "Admin Completed" / "Building Administration" permits) remain without PERMIT_DATE, as these permit types do not have a meaningful issuance step.

### FINAL_DATE (1 repair: 1 FILLED)

1 record has FINAL_DATE missing but `Completed` present in DATA. This is the STATUS_ORIGINAL/Permit Status mismatch record (STATUS_ORIGINAL = "issued", DATA Permit Status = "Final") which was categorised as "Active" and therefore didn't receive a FINAL_DATE during initial processing. After fixing the status to "Final", FINAL_DATE is filled from Completed = "07/26/2024".

The remaining 1 missing FINAL_DATE among "Final" records is a "Closed" permit with no Completed date in DATA.

## Post-repair quality

| Field | Status group | Coverage |
|---|---|---|
| STATUS_NORMALIZED | all | 2,001 / 2,001 (100%) |
| FILE_DATE | all | 1,991 / 2,001 (99.5%) |
| PERMIT_DATE | Active + Final | 516 / 688 (75.0%) |
| FINAL_DATE | Final | 459 / 460 (99.8%) |

## Artifacts

- **Repair script**: `agent/scripts/burbank_data_repair.py`
  - Function `data_repair(df)` takes a Burbank-filtered DataFrame, returns a copy with corrected values and `{FIELD}_FLAG` columns ("FILLED" or "FIXED").
  - Includes a CLI entrypoint that prints repair statistics when run standalone.
