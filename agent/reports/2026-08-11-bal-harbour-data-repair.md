# Bal Harbour (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Lakeland in list order) was **Bal Harbour**. DATA is mostly civic eTRAKiT (`permit_info`, 1,578 rows) plus 422 empty alternate-portal shells with no usable fields. The largest defect was STATUS_NORMALIZED: **935** nulls, of which **513** civic rows were filled (mainly 499 `IMPORTED` inferred from Issued/Finaled dates). Date fields already matched Applied/Issued when present; the main date win was FINAL_DATE (**327 FILLED**, mostly CLOSED rows whose `PermitFinaledDate` is the `1/1/2999` sentinel, recovered from approved inspections). After repair, civic FILE_DATE is 100%, Active PERMIT_DATE is 98.2%, Final PERMIT_DATE is 99.1%, and Final FINAL_DATE is 91.5%. The 422 empty-shell rows remain fully missing.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County through Babcock Ranch / Aventura / etc.; **Bal Harbour** was the first without `agent/scripts/fl/data_repair_fl_bal_harbour.py`.

Sample size: **2,000** records.

## DATA schemas

| INFERRED_SCHEMA       | Count |
| --------------------- | ----: |
| `civic_issued`        |   842 |
| `civic_issued_finaled`|   618 |
| `empty_shell`         |   422 |
| `civic_applied`       |    80 |
| `civic_approved`      |    33 |
| `civic_finaled`       |     5 |

Canonical source fields (civic only):

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (+ Issued/Finaled for `IMPORTED` / gated labels) |
| FILE_DATE         | `PermitAppliedDate`                                                         |
| PERMIT_DATE       | `PermitIssuedDate` (years outside 1980–2035 treated as missing)             |
| FINAL_DATE        | `PermitFinaledDate` else last approved final-ish inspection else last approved inspection (Final only) |

`empty_shell` rows expose keys such as `Build Status` / `Permit Details` but every value is null or `{}` / `[]` — not repairable.

## Field assessments

### STATUS_NORMALIZED

Before: Final 775 · Inactive 123 · Active 122 · In Review 45 · missing 935.

- Live `PermitStatus` agrees with `STATUS_ORIGINAL` on 1,553 / 1,578 civic rows; the 25 mismatches are stale snapshots (e.g. `issued`/`ready` while live status is `FINALED`).
- **513 FILLED** nulls on civic rows:
  - `IMPORTED` (499): Final if usable FinaledDate (228), Active if Issued only (269), In Review if neither (2). Many FinaledDates are the `1/1/2999` sentinel and are ignored.
  - Plus `FIRST REVIEW` (6), `CC` (3), `EARLY START APPROVAL` (1), `EARLY START APPROVAL EXPIRED` (1), `TCC` (1), `NOT SUBMITTED` (1), `WRITTEN WARNING` (1).
- **26 FIXED**: mainly 13 `FINALED` mislabeled Active/In Review/Inactive → Final; 5 `ISSUED` mislabeled In Review/Inactive/Final → Active; 3 unissued `APPROVED` Active → In Review; `CC`/`CO`/`CLOSED` Active → Final; one each for `ON REVIEW` / `READY` Inactive → In Review.
- **422** empty-shell rows stay missing (no status in DATA).

After: Final 1,022 · Active 381 · Inactive 121 · In Review 54 · missing 422.  
Flags: **FILLED 513 · FIXED 26**.

### FILE_DATE

Before: 422 missing (all empty-shell). Ideal: populated for all records.

- On civic rows, FILE_DATE already matched `PermitAppliedDate` on **1,578 / 1,578** comparable rows (0 day mismatches, 0 fills needed).
- Empty-shell rows have no Applied date → remain missing.

After: 422 missing (78.9% overall; **100%** of civic).  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 545 missing. Ideal: populated for Active and Final.

- When both present, PERMIT_DATE already matched Issued (**0** day mismatches). Sentinel `1/1/2999` IssuedDates are rejected.
- **5 FILLED** after status remaps brought Issued rows into Active/Final with null PERMIT_DATE.
- Remaining Active gaps (7): `ISSUED`/`ACTIVE` labels with blank or sentinel IssuedDate in DATA.

After: 540 missing. Coverage: Active **98.2%** (374/381); Final **99.1%** (1,013/1,022).  
Flags: **FILLED 5 · FIXED 0**.

### FINAL_DATE

Before: 1,388 missing; Final coverage only 376/775 (48.5%). Ideal: populated for Final.

- Upstream left FINAL_DATE null whenever `PermitFinaledDate` was empty or `1/1/2999` (698 sentinel FinaledDates in the sample).
- **298 FILLED** on `CLOSED` Final rows from last approved inspection Completed date.
- **27 FILLED** on `FINALED` / certificate-style rows from FinaledDate or inspections.
- **4 FIXED**: cleared spurious FINAL_DATE on non-Final remaps (`ISSUED`→Active, `CANCELLED`/`EXPIRED`/`EARLY START APPROVAL EXPIRED`→Inactive).
- **87** Final rows still lack FINAL_DATE (68 `CLOSED`, 18 `FINALED`, 1 `CERTIFICATE OF OCCUPANCY`) — no usable FinaledDate and no approved inspection.

After: 1,065 missing. Final coverage **91.5%** (935/1,022). Non-Final FINAL_DATE: **0**.  
Flags: **FILLED 327 · FIXED 4**.

## Repair script

- Script: `agent/scripts/fl/data_repair_fl_bal_harbour.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/bal_harbour_repaired_sample.parquet`
