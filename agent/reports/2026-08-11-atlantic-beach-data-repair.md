# Atlantic Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Apopka / Arcadia / … through existing FL scripts in list order) was **Atlantic Beach**. DATA is Accela-style JSON (`permit_info` / `search_data` / `inspections`). STATUS_NORMALIZED was filled on 8 unmapped portal statuses. FILE_DATE already matched `PermitAppliedDate` wherever present (1,111 CONV blanks remain unrepaired). PERMIT_DATE gained 31 fills from `PermitApprovedDate` when Issued was blank. FINAL_DATE gained 401 fills from approved inspections on Final rows; 1 Inactive withdrawn row incorrectly carrying FINAL_DATE was cleared.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County through Arcadia (and other later cities already scripted). **Atlantic Beach** was the first without `agent/scripts/fl/data_repair_fl_atlantic_beach.py`.

Sample size: **2,000** records.

## DATA schemas

All rows share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Content variants by which `permit_info` dates are populated:

| INFERRED_SCHEMA         | Count |
| ----------------------- | ----: |
| `accela_issued_finaled` | 1,175 |
| `accela_issued`         |   724 |
| `accela_applied`        |    38 |
| `accela_finaled`        |    32 |
| `accela_status_only`    |    18 |
| `accela_approved`       |    13 |

Canonical source fields:

| Target field      | DATA source                                                          |
| ----------------- | -------------------------------------------------------------------- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` else `search_data.STATUS`                 |
| FILE_DATE         | `permit_info.PermitAppliedDate`                                      |
| PERMIT_DATE       | `PermitIssuedDate`, else `PermitApprovedDate` (Active/Final)         |
| FINAL_DATE        | `PermitFinaledDate`, else latest approved final-ish / any inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,784 · Active 149 · Inactive 35 · In Review 24 · missing 8.

- Existing non-null mappings from `STATUS_ORIGINAL` / `PermitStatus` were already correct (`finaled`/`closed`/`closed no inspection`→Final; `issued`/`approved`→Active; review-like statuses→In Review; cancelled/expired/withdrawn→Inactive).
- **8** rows had null STATUS_NORMALIZED because upstream never mapped:
  - `awaiting corrections` (4) → **FILLED** In Review
  - `pre issuance` (2) → **FILLED** In Review
  - `in-active` (2) → **FILLED** Inactive
- No incorrect non-null statuses needed fixing. Unlike Coral Springs, no Active rows carried a stale `PermitFinaledDate`.

After: Final 1,784 · Active 149 · Inactive 37 · In Review 30 · missing 0.  
Flags: **FILLED 8 · FIXED 0**.

### FILE_DATE

Before: 1,111 missing. Ideal: populated for all records.

- Upstream FILE_DATE matched `PermitAppliedDate` on every row where both were present (**0** day mismatches).
- All 1,111 missing rows are CONV-legacy conversions (`RECORDID` starts with `CONV:`) with blank `PermitAppliedDate`. Issued/Approved/Finaled dates exist on many of these but are not application/submittal dates, so they were not used as FILE_DATE proxies.

After: 1,111 missing. Coverage: Active **93.3%**; Final **39.4%**; In Review **40.0%**; Inactive **94.6%**.  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 101 missing (65 of Active/Final). Ideal: populated for Active and Final.

- When present, PERMIT_DATE already matched `PermitIssuedDate` (**0** mismatches) and `search_data.ISSUED`.
- **31** Active/Final rows had blank Issued but a usable `PermitApprovedDate` → **FILLED** (approval is a valid PERMIT_DATE under the project definition; when both Issued and Approved exist, Issued is typically 0–3 days later).
- **34** Active/Final rows still lack both Issued and Approved → not repairable from DATA (includes several `approved` / `finaled` / `closed no inspection` shells).
- Inactive/In Review rows retain upstream Issued-based PERMIT_DATE when present; Approved-only fallback is restricted to Active/Final.

After: 70 missing. Coverage: Active **96.0%**; Final **98.4%**.  
Flags: **FILLED 31 · FIXED 0**.

### FINAL_DATE

Before: 793 missing (578 of Final); 1 Inactive (`withdrawn`) incorrectly carried FINAL_DATE. Ideal: populated for Final.

- When present, FINAL_DATE already matched `PermitFinaledDate` (**0** mismatches).
- Among Final rows still missing FINAL_DATE, filled from inspections: **332** from approved final-ish types (`*FINAL*`, certificate of completion, etc.), **69** from latest other approved inspection.
- **177** Final rows remain without FINAL_DATE (empty / non-approved inspections + blank finaled), dominated by `closed no inspection` and sparse CONV shells.
- The withdrawn Inactive row’s FINAL_DATE was **FIXED** (cleared); non-Final rows should not carry completion dates.

After: 393 missing. Coverage: Final **90.1%**; Active/In Review/Inactive **0%**.  
Flags: **FILLED 401 · FIXED 1**.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_atlantic_beach.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.

## Performance summary

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | -----: | ----: | -------------: | ------------: |
| STATUS_NORMALIZED |      8 |     0 |              8 |             0 |
| FILE_DATE         |      0 |     0 |          1,111 |         1,111 |
| PERMIT_DATE       |     31 |     0 |            101 |            70 |
| FINAL_DATE        |    401 |     1 |            793 |           393 |

## Artifacts

- Repaired sample: `AGENT_DATA_PATH/atlantic_beach_repaired_sample.parquet`
