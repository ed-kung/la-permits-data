# Bay County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Bal Harbour in list order) was **Bay County**. DATA is a single civic eTRAKiT family (`permit_info`, all 2,001 rows). Upstream dates already matched Applied/Issued/Finaled when present; repairs focused on status gaps (6 null labels + 10 unissued `APPROVED` Active→In Review), clearing 13 spurious non-Final `FINAL_DATE` values, and filling 4 Final `FINAL_DATE` gaps from approved inspections. After repair: STATUS fully populated; FILE_DATE 99.6%; Active PERMIT_DATE 97.8%; Final PERMIT_DATE 99.7%; Final FINAL_DATE 96.0%; non-Final FINAL_DATE 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County through Bal Harbour (and other out-of-order cities). **Bay County** was the first without `agent/scripts/fl/data_repair_fl_bay_county.py`.

Sample size: **2,001** records.

## DATA schemas

| INFERRED_SCHEMA        | Count |
| ---------------------- | ----: |
| `civic_issued_finaled` | 1,250 |
| `civic_issued`         |   635 |
| `civic_applied`        |    83 |
| `civic_approved`       |    19 |
| `civic_finaled`        |     7 |
| `civic_status_only`    |     7 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (+ Issued/Finaled gating for `APPROVED`)         |
| FILE_DATE         | `PermitAppliedDate`                                                         |
| PERMIT_DATE       | `PermitIssuedDate` (years outside 1980–2035 treated as missing)             |
| FINAL_DATE        | `PermitFinaledDate` else last approved final-ish inspection else last approved inspection (Final only) |

`STATUS_ORIGINAL` matches live `PermitStatus` on all 2,001 rows (case variants such as `Issued` / `Applied` normalize via uppercasing).

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,299 · Active 556 · In Review 73 · Inactive 67 · missing 6.

- Upstream mapping was already correct for common labels (`finaled`→Final, `issued`→Active, `applied`→In Review, `expired`/`void`/`withdrawn`/`abandoned`/`refunded`→Inactive, `pending`/`hold`/`paid`→In Review, `coc`→Final).
- **6 FILLED** nulls:
  - `bldr app` (4) → In Review
  - `addr app` (1) → In Review
  - `c/o` (1) → Final
- **10 FIXED**: unissued `APPROVED` labeled Active → In Review (1 issued `APPROVED` correctly stays Active).

After: Final 1,300 · Active 546 · In Review 88 · Inactive 67 · missing 0.  
Flags: **FILLED 6 · FIXED 10**.

### FILE_DATE

Before: 9 missing. Ideal: populated for all records.

- When both present, FILE_DATE already matched `PermitAppliedDate` on **1,992 / 1,992** rows (0 day mismatches).
- The 9 missing rows have blank Applied dates in DATA (mostly `APPLIED`, plus one `ISSUED` and one `ADDR APP`) → not fillable.

After: 9 missing (99.6% overall).  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 116 missing. Ideal: populated for Active and Final.

- When both present, PERMIT_DATE already matched Issued (**0** day mismatches).
- Remapping 10 unissued `APPROVED` to In Review removes their PERMIT_DATE expectation; no Issued date was available to fill Active/Final gaps.
- Remaining Active gaps (12): `ISSUED` with blank `PermitIssuedDate`. Final gaps (4): `FINALED` with blank Issued.

After: 116 missing. Coverage: Active **97.8%** (534/546); Final **99.7%** (1,296/1,300).  
Flags: **FILLED 0 · FIXED 0**.

### FINAL_DATE

Before: 744 missing; Final coverage 1,244/1,299 (95.8%). Ideal: populated for Final.

- When both present, FINAL_DATE already matched Finaled (**0** day mismatches).
- **13 FIXED**: cleared spurious FINAL_DATE on non-Final rows whose DATA still carried `PermitFinaledDate` while `PermitStatus` remained `ISSUED` / `APPLIED` / `PAID` (agency status left unchanged; Finaled treated as stale relative to status).
- **4 FILLED** on `FINALED` rows from last approved inspection Completed date (blank FinaledDate).
- **52** Final rows still lack FINAL_DATE — blank FinaledDate and no usable approved inspection (including the filled `C/O` row).

After: 753 missing. Final coverage **96.0%** (1,248/1,300). Non-Final FINAL_DATE: **0**.  
Flags: **FILLED 4 · FIXED 13**.

## Artifacts

| Path | Description |
| ---- | ----------- |
| `agent/scripts/fl/data_repair_fl_bay_county.py` | `data_repair()` implementation |
| `AGENT_DATA_PATH/bay_county_repaired_sample.parquet` | Repaired sample with flag + `INFERRED_SCHEMA` columns |
