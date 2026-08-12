# Lakeland (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Palm Beach County in list order) was **Lakeland**. DATA has two portal families — civic eTRAKiT (`permit_info`) and Accela IMS (`Permit` / `ViewMilestones`). STATUS_NORMALIZED was filled on 7 unmapped labels and fixed on 178 rows — mainly 117 `CLOSED ADMIN` and 52 `HB447 CLOSED` mislabeled as Final. FILE_DATE gained 2 fills and 2 calendar-day fixes vs Submitted. PERMIT_DATE needed only 1 fill. The largest date win was FINAL_DATE: **491 FILLED** from `PermitFinaledDate` / `ViewMilestones.Finaled` (plus 5 spurious non-Final clears). After repair, FILE_DATE is 99.8%, Active PERMIT_DATE is 98.2%, Final PERMIT_DATE is 79.9%, and Final FINAL_DATE is 79.7%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in file order. Existing FL repair scripts covered Jacksonville through Palm Beach County. **Lakeland** was the first without `agent/scripts/fl/data_repair_fl_lakeland.py`.

Sample size: **2,002** records.

## DATA schemas

| INFERRED_SCHEMA          | Count |
| ------------------------ | ----: |
| `civic_issued_finaled`   |   832 |
| `accela_issued_finaled`  |   490 |
| `civic_applied`          |   320 |
| `accela_applied`         |   146 |
| `accela_issued`          |   106 |
| `civic_issued`           |    96 |
| `civic_finaled`          |     6 |
| `civic_status_only`      |     4 |
| `accela_status_only`     |     2 |

Canonical source fields:

| Target field      | Civic DATA                         | Accela DATA                                      |
| ----------------- | ---------------------------------- | ------------------------------------------------ |
| STATUS_NORMALIZED | `permit_info.PermitStatus`         | `Permit.Milestone`                               |
| FILE_DATE         | `PermitAppliedDate`                | `ViewMilestones.Submitted` (fallback `Created`)  |
| PERMIT_DATE       | `PermitIssuedDate`                 | `ViewMilestones.Issued`                          |
| FINAL_DATE        | `PermitFinaledDate` (Final only)   | `ViewMilestones.Finaled` (Final only)            |

`PermitApprovedDate` / `Approved` are not used for PERMIT_DATE (approval ≠ issuance).

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,827 · Inactive 73 · Active 61 · In Review 34 · missing 7.

- `STATUS_ORIGINAL` matches the live portal status on nearly every row (2 stale `issued` snapshots); defects are mostly in the upstream normalize map.
- **7 FILLED** nulls: `ABANDONED/FBC CH1`→Inactive (2), `Approved Pending Payment`→In Review (2), `NOC REQUIRED`→In Review (1), `Revisions Pending` with Issued→Active (1), `SWO`→Inactive (1).
- **117** `CLOSED ADMIN` and **52** `HB447 CLOSED` rows were labeled Final but almost never have a finaled date (2 and 1 respectively) → **FIXED** to Inactive (same rationale as Palm Beach `Admin Closed` / Alachua admin closures).
- **5** unissued `APPROVED` rows labeled Active → **FIXED** to In Review.
- **2** `EVENT COMPLETED` special-event rows labeled In Review → **FIXED** to Final.
- **1** Accela `Finaled` row with stale `STATUS_ORIGINAL=issued` labeled Active → **FIXED** to Final.
- **1** Accela `Under Review` row with stale `STATUS_ORIGINAL=issued` labeled Active → **FIXED** to In Review.

After: Final 1,661 · Inactive 245 · Active 55 · In Review 41 · missing 0.  
Flags: **FILLED 7 · FIXED 178**.

### FILE_DATE

Before: 7 missing. Ideal: populated for all records.

- Upstream matched Applied/Submitted on **1,992 / 1,994** comparable rows.
- **2 FILLED** from Accela `Submitted` where FILE_DATE was null.
- **2 FIXED** where FILE_DATE matched `Created` but `Submitted` differed (prefer submittal date).
- **5** remain missing: empty civic `PermitAppliedDate` (4) and one Accela `Issued` row with empty `ViewMilestones`.

After: 5 missing (99.8% coverage).  
Flags: **FILLED 2 · FIXED 2**.

### PERMIT_DATE

Before: 477 missing. Ideal: populated for Active and Final.

- When present, PERMIT_DATE already matched Issued (**0** day mismatches).
- Status remaps moved unissued `APPROVED` out of Active, so Active coverage is nearly complete without inventing dates.
- **1 FILLED**: Accela Final row with `Issued` in DATA but null PERMIT_DATE.
- Remaining gaps are mostly legacy `FINALED` / remapped Inactive rows with no Issued date in DATA. One Active `Issued` row has empty milestones → not repairable.

After: 476 missing. Coverage: Active **98.2%** (54/55); Final **79.9%** (1,327/1,661).  
Flags: **FILLED 1 · FIXED 0**.

### FINAL_DATE

Before: 1,165 missing; Final coverage only 835/1,827 (45.7%). Ideal: populated for Final.

- When both present, FINAL_DATE already matched finaled (**0** mismatches).
- Large upstream gap on Accela: many `Finaled` / `FINALED` rows had `ViewMilestones.Finaled` populated but null FINAL_DATE → **491 FILLED**.
- **5 FIXED** clears of spurious FINAL_DATE after status remap / on Inactive `CANCELLED` / `CLOSED ADMIN` / `HB447 CLOSED` rows.
- Remaining Final gaps (338) have Milestone/Status final-like but no finaled date in DATA (`FINALED` civic 240, Accela 90, plus `CLOSED` / `EVENT COMPLETED` without a Finaled stamp).

After: 679 missing. Coverage: Final **79.7%** (1,323/1,661); Active / In Review / Inactive **0%**.  
Flags: **FILLED 491 · FIXED 5**.

## Repair script

`agent/scripts/fl/data_repair_fl_lakeland.py` — function `data_repair(df)`.

Adds `INFERRED_SCHEMA` and `{STATUS_NORMALIZED,FILE_DATE,PERMIT_DATE,FINAL_DATE}_FLAG` (`FILLED` / `FIXED`).

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_lakeland.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/lakeland_repaired_sample.parquet`
