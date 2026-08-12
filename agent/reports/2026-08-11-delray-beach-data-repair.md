# Delray Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Delray Beach**. DATA is mostly Tyler EnerGov (`entity_fees_reviews`, 1,947) plus a legacy `permit_inspections` portal schema (55). Upstream entity FILE/PERMIT/FINAL dates already matched ApplyDate/IssueDate/FinalDate when present. Repairs filled 4 null statuses (early-review labels), remapped 1 Issued+FinalDate row Active→Final, filled 9 missing FINAL_DATE values (2 from Passed final inspections, 7 from Approved final Inspection List dates), and cleared 1 spurious FINAL_DATE on Expired Closed. After repair: STATUS fully populated; FILE_DATE 100% on entity rows (55 legacy shells still blank); Active PERMIT_DATE 99.2%; Final PERMIT_DATE 87.2%; Final FINAL_DATE 93.8%; non-Final FINAL_DATE 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing FL repair scripts covered Jacksonville through Brevard County. **Delray Beach** was the first without `agent/scripts/fl/data_repair_fl_delray_beach.py`.

Sample size: **2,002** records.

## DATA schemas

| INFERRED_SCHEMA        | Count |
| ---------------------- | ----: |
| `entity_fees_reviews`  | 1,947 |
| `permit_inspections`   |    55 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`); or `Permit.Application Status` |
| FILE_DATE         | `entity.ApplyDate` / `details.ApplyDate` (entity only)                      |
| PERMIT_DATE       | `entity.IssueDate` / `details.IssueDate` (entity only)                      |
| FINAL_DATE        | `entity.FinalDate` else `details.FinalizeDate` else latest Passed final-ish `processing_status` inspection; or latest Approved final-ish `Inspection List` date (permit schema) |

`STATUS_ORIGINAL` matches live CaseStatus / Application Status on **all** sample rows (no stale original labels).

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,814 · Active 120 · Inactive 39 · In Review 25 · missing 4.

- Common labels were already mapped (`complete`/`closed`/`administratively closed`/`c.o. issued`→Final, `issued`→Active, `void`/`expired closed`→Inactive, `in review`/`on hold`/`fees due`→In Review).
- **4 FILLED** nulls from early-pipeline CaseStatus labels:
  - `New Document` (2), `Upload and Submit` (1), `Respond and Resubmit` (1) → In Review
- **1 FIXED**: `Issued` Active→Final — CaseStatus still `Issued` but `FinalDate` present (Passed Building Final in processing_status); treated as portal status lag so FINAL_DATE is retained.

After: Final 1,815 · Active 119 · Inactive 39 · In Review 29 · missing 0.  
Flags: **FILLED 4 · FIXED 1**.

### FILE_DATE

Before: 55 missing (all `permit_inspections`). Ideal: populated for all records.

- Entity FILE_DATE already matched the UTC calendar date of `ApplyDate` on **1,947 / 1,947** rows.
- Legacy `permit_inspections` rows have no ApplyDate (or equivalent) in DATA → not fillable.

After: 55 missing. Coverage: Active / In Review / Inactive **100%**; Final **97.0%** (1,760/1,815).  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 264 missing. Ideal: populated for Active and Final.

- When both present, entity PERMIT_DATE already matched IssueDate (**0** day mismatches).
- No Active/Final rows had IssueDate while PERMIT_DATE was blank → nothing to fill.
- Remaining gaps: Final shells with Issued=False / null IssueDate (Complete/Closed/Administratively Closed and all 55 legacy rows); 1 Issued Active shell with Issued=False / null IssueDate. Plan Review / Inspection List dates on the legacy schema do not reliably match existing PERMIT_DATE values, so they were not used.

After: 264 missing. Coverage: Active **99.2%** (118/119); Final **87.2%** (1,582/1,815).  
Flags: **FILLED 0 · FIXED 0**.

### FINAL_DATE

Before: 307 missing; Final coverage 1,695/1,814 (93.4%). Ideal: populated for Final; absent otherwise.

- When both present, entity FINAL_DATE already matched FinalDate (**0** day mismatches); FinalDate ≈ FinalizeDate on all non-null rows.
- **9 FILLED**:
  - 2 Closed Final rows from Passed final-ish `processing_status` inspections (no FinalDate/FinalizeDate)
  - 7 `permit_inspections` C.O. ISSUED rows from Approved final Inspection List dates
- **1 FIXED**: cleared spurious FINAL_DATE on Inactive `Expired Closed` (case-closure FinalDate, not a successful permit sign-off).
- The Issued+FinalDate row kept its FINAL_DATE after status remap to Final (no flag; value was already correct vs FinalDate).
- Remaining Final gaps (~112): mostly Closed entity shells and legacy rows with no FinalDate and no usable Approved/Passed final inspection.

After: 299 missing. Coverage: Final **93.8%** (1,703/1,815); non-Final **0**.  
Flags: **FILLED 9 · FIXED 1**.

## Artifacts

| Path | Description |
| ---- | ----------- |
| `agent/scripts/fl/data_repair_fl_delray_beach.py` | `data_repair()` implementation |
| `AGENT_DATA_PATH/delray_beach_repaired_sample.parquet` | Repaired sample with flag + INFERRED_SCHEMA columns |
