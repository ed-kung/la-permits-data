# Deerfield Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (parquet encounter order after Margate) was **Deerfield Beach** (2,001 records). DATA is a single `city_portal` schema (`Permit Information` + `Applications` + `Inspections History`). STATUS_NORMALIZED: 54 FILLED + 7 FIXED (nulls 54→0). FILE_DATE already matched earliest `AppDate` on every row (0 changes). PERMIT_DATE: 242 FIXED — 214 overwritten from `ApprovedByDate`, 28 spurious In Review copies cleared. FINAL_DATE: 1,437 FILLED from Passed FINAL inspections (Final coverage 0%→88.4%).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Deerfield Beach, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` in parquet encounter order)
- Script: `agent/scripts/fl/data_repair_fl_deerfield_beach.py`
- Artifact: `AGENT_DATA_PATH/deerfield_beach_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `city_portal` | 2,001 | Top-level `Applications`, `Fees and Payments`, `Permit Information`, `Inspections History`, `Permit Requirements`, `Plan Review History` |

All rows share the same key set; no sub-schema split was needed.

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,622; Inactive 251; null 54; Active 47; In Review 27
- Canonical source: `Permit Information[0].StatusDesc` (matches `STATUS_ORIGINAL` case-insensitively on nearly all rows; defects are upstream normalize gaps / stale labels).
- **FILLED (54):** unmapped CU/BTR labels — CU Issued→Active (33), BTR Outstanding→Inactive (8), BTR Out of Business→Inactive (7), BTR Issued→Active (4), CU PreApproved→In Review (2).
- **FIXED (7):** 5 `Permit Complete` rows labeled Active (stale `STATUS_ORIGINAL=permit issued`)→Final; 1 `Permit Issued` labeled In Review→Active; 1 `CU Issued` labeled Final→Active.
- After: Final 1,626; Inactive 266; Active 81; In Review 28; null 0

### FILE_DATE

- Ideal: populated for all records.
- Source: earliest `Applications[].AppDate` (equals earliest `DateCreated` in this sample).
- Already correct on all 2,001 rows. **0 FILLED / 0 FIXED.**
- After: 100% coverage for every status.

### PERMIT_DATE

- Ideal: populated for Active and Final; not for unissued In Review.
- Upstream set PERMIT_DATE = FILE_DATE on every row. Only 230 rows have any `ApprovedByDate`; that field is the approval/issuance signal.
- Repair: for Active/Final/Inactive, overwrite from earliest `ApprovedByDate` when present; for In Review, clear the spurious FILE_DATE copy.
- **0 FILLED + 242 FIXED** (214 date overwrites + 28 In Review clears).
- After: Active 81/81 (100%); Final 1,626/1,626 (100%); In Review 0/28; Inactive 266/266.
- Caveat: 1,499 Active/Final rows still have PERMIT_DATE == FILE_DATE because DATA has no `ApprovedByDate` (and no other reliable issuance field). Left as-is rather than clearing, to preserve ideal coverage.

### FINAL_DATE

- Ideal: populated for Final.
- Before: missing on all 2,001 rows (100%).
- Source: latest inspection with `statusdesc == "Passed"` and `"FINAL"` in `inspectiondesc` (`scheduleddate`).
- **1,437 FILLED + 0 FIXED.**
- Not repairable: 137 Final rows with empty inspection history; 52 Final rows with inspections but no Passed FINAL (mostly old non-final passed-only history).
- After: Final 1,437/1,626 (88.4%); non-Final FINAL_DATE all null.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 54 | 7 | 54 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 242 | 0 → 28 |
| FINAL_DATE | 1,437 | 0 | 2,001 → 564 |

Ideal-field coverage after repair:

- FILE_DATE: 100% of all statuses
- PERMIT_DATE: 100% of Active / Final; 0% of In Review
- FINAL_DATE: 88.4% of Final; 0% of non-Final

Post-repair checks: STATUS nulls eliminated; In Review no longer carries copied PERMIT_DATE; PERMIT>FINAL inversions = 1 (source quirk: `ApprovedByDate` 2022-10-07 vs Passed WINDOW/DOOR FINAL 2022-10-05 — left as-is).

## Artifacts

- `agent/scripts/fl/data_repair_fl_deerfield_beach.py`
- `AGENT_DATA_PATH/deerfield_beach_repaired_sample.parquet`
