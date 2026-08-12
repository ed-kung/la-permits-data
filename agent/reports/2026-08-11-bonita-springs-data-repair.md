# Bonita Springs (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Boca Raton in list order) was **Bonita Springs**. DATA is Tyler EnerGov-style (`entity`/`details`/`fees`, 2 schemas). Upstream FILE/PERMIT/FINAL dates already matched ApplyDate/IssueDate/FinalDate when present; repairs focused on status gaps and drift vs live `CaseStatus` (42 null + 55 remapped), filling 8 Active PERMIT_DATE and 24 Final FINAL_DATE gaps (FinalDate after status fix, or Passed final inspections), and clearing 3 spurious non-Final FINAL_DATE values. After repair: STATUS fully populated; FILE_DATE 100%; Active PERMIT_DATE 100%; Final PERMIT_DATE 91.1%; Final FINAL_DATE 99.3%; non-Final FINAL_DATE 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County through Boca Raton (and other out-of-order cities). **Bonita Springs** was the first without `agent/scripts/fl/data_repair_fl_bonita_springs.py`.

Sample size: **2,001** records.

## DATA schemas

| INFERRED_SCHEMA        | Count |
| ---------------------- | ----: |
| `entity_fees`          | 1,926 |
| `entity_fees_reviews`  |    75 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`)                        |
| FILE_DATE         | `entity.ApplyDate` / `details.ApplyDate`                                    |
| PERMIT_DATE       | `entity.IssueDate` / `details.IssueDate`                                    |
| FINAL_DATE        | `entity.FinalDate` else `details.FinalizeDate` else latest Passed final-ish inspection in `processing_status` (Final only) |

`STATUS_ORIGINAL` matches live `CaseStatus` on **1,971 / 2,001** rows; the 30 mismatches are stale original labels (e.g. `issued` while CaseStatus is now `Finaled` / `Expired` / `Void`).

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,548 · Active 188 · Inactive 132 · In Review 91 · missing 42.

- Common labels were already mapped (`finaled`/`completed`→Final, `issued`→Active, `expired`/`void`/`withdrawn`→Inactive, `review in progress`/`ready for issuance`/`hearing scheduled`→In Review).
- **42 FILLED** nulls from previously unmapped CaseStatus labels:
  - `Void - No Refund` (14), void-refund variants (3) → Inactive
  - `Temporary Use Expired` (10) → Inactive
  - `Pending Applicant Documentation` (8), `RAI` (2), `Intake Review` (2), `Ready for Issuance` (1) → In Review
  - `Issued` (1), `Expired` (1) → Active / Inactive
- **55 FIXED** against live CaseStatus:
  - `Approved` Active→Final (18) — planning/admin cases with FinalDate and usually no IssueDate
  - `Finaled` Active/In Review/Inactive→Final (13) — stale STATUS_ORIGINAL (`issued` / etc.)
  - `Not Approved` In Review→Inactive (8)
  - `Issued` In Review→Active (7)
  - `Zoning Approved` In Review→Active (5) — Issued=True with IssueDate
  - `Expired`/`Void` Active→Inactive (4)

After: Final 1,579 · Inactive 171 · Active 168 · In Review 83 · missing 0.  
Flags: **FILLED 42 · FIXED 55**.

### FILE_DATE

Before: 0 missing. Ideal: populated for all records.

- FILE_DATE already matched the UTC calendar date of `ApplyDate` on **2,001 / 2,001** rows.

After: 0 missing (100%).  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 306 missing. Ideal: populated for Active and Final.

- When both present, PERMIT_DATE already matched IssueDate (**0** day mismatches).
- **8 FILLED**: Issued rows remapped to Active (7 previously In Review + 1 previously null) that already had IssueDate but blank PERMIT_DATE.
- Remaining Final gaps (140): mostly `Completed` / `Approved` administrative cases and some `Finaled` shells with Issued=False / null IssueDate — not fillable from DATA.

After: 298 missing. Coverage: Active **100%** (168/168); Final **91.1%** (1,439/1,579).  
Flags: **FILLED 8 · FIXED 0**.

### FINAL_DATE

Before: 454 missing; Final coverage 1,526/1,548 (98.6%). Ideal: populated for Final; absent otherwise.

- When both present, FINAL_DATE already matched FinalDate (**0** day mismatches); FinalDate ≈ FinalizeDate on all non-null rows.
- **24 FILLED**:
  - 13 from FinalDate once stale Active/In Review/Inactive `Finaled` rows were remapped to Final
  - 11 from Passed final-ish inspections when FinalDate/FinalizeDate were blank
- **3 FIXED**: cleared spurious FINAL_DATE on Void / Void-refund / Not Approved rows (case-closure FinalDate, not a permit sign-off).
- **11** Final rows still lack FINAL_DATE — blank FinalDate and no usable Passed final inspection (mostly temporary-use / imported home-occupation / pre-application shells).

After: 433 missing. Final coverage **99.3%** (1,568/1,579). Non-Final FINAL_DATE: **0**.  
Flags: **FILLED 24 · FIXED 3**.

## Artifacts

| Path | Description |
| ---- | ----------- |
| `agent/scripts/fl/data_repair_fl_bonita_springs.py` | `data_repair()` implementation |
| `$AGENT_DATA_PATH/bonita_springs_repaired_sample.parquet` | Repaired sample with flag + INFERRED_SCHEMA columns |
