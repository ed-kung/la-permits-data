# Coral Springs (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Orange County / Miramar / Boca Raton in list order) was **Coral Springs**. DATA is Accela-style JSON (`permit_info` / `search_data` / `inspections`). STATUS_NORMALIZED was filled on 7 shells and fixed on 17 legacy `approved` rows that already had `PermitFinaledDate` (Active→Final). FILE_DATE already matched `PermitAppliedDate` wherever present (9 blanks remain unrepaired). PERMIT_DATE gained 69 fills from `PermitApprovedDate` when Issued was blank. FINAL_DATE gained 237 fills from approved inspections on Final rows; non-Final rows no longer carry final dates after the status upgrade.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in file order. Existing FL repair scripts covered Jacksonville through Orange County. **Coral Springs** was the first without `agent/scripts/fl/data_repair_fl_coral_springs.py`.

Sample size: **2,001** records.

## DATA schemas

All rows share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Content variants by which `permit_info` dates are populated:

| INFERRED_SCHEMA           | Count |
| ------------------------- | ----: |
| `accela_issued_finaled`   | 1,145 |
| `accela_issued`           |   480 |
| `accela_applied`          |   208 |
| `accela_finaled`          |   124 |
| `accela_approved`         |    35 |
| `accela_status_only`      |     9 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` else `search_data.STATUS`; finaled date → Final |
| FILE_DATE         | `permit_info.PermitAppliedDate`                                             |
| PERMIT_DATE       | `PermitIssuedDate`, else `PermitApprovedDate` (Active/Final)                |
| FINAL_DATE        | `PermitFinaledDate`, else latest approved final-ish / any inspection        |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,756 · Inactive 141 · Active 80 · In Review 17 · missing 7.

- Existing non-null mappings from `STATUS_ORIGINAL` / `PermitStatus` were already correct (`closed`/`cert of occupancy`/`cert of completion`→Final; `approved`/`issued`→Active; review statuses→In Review; cancelled/expired/revoked/void→Inactive).
- **7** conversion shells had blank `permit_info.PermitStatus` but `search_data.STATUS` in {CLOSED, CERT OF OCCUPANCY, CERT OF COMPLETION} → **FILLED** as Final.
- **17** `approved` / Active rows carried a non-null `PermitFinaledDate` (often with approved final inspections). Portal status was stale; **FIXED** to Final.

After: Final 1,780 · Inactive 141 · Active 63 · In Review 17 · missing 0.  
Flags: **FILLED 7 · FIXED 17**.

### FILE_DATE

Before: 9 missing. Ideal: populated for all records.

- Upstream FILE_DATE matched `PermitAppliedDate` on every row where both were present (**0** day mismatches).
- The 9 missing rows are status-only shells (blank applied/issued/finaled/approved in `permit_info`); no alternate application timestamp in DATA.

After: 9 missing. Coverage: Active / In Review **100%**; Final **99.6%**; Inactive **98.6%**.  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 376 missing (285 of Active/Final). Ideal: populated for Active and Final.

- When present, PERMIT_DATE already matched `PermitIssuedDate` (**0** mismatches).
- **69** Active/Final rows had blank Issued but a usable `PermitApprovedDate` → **FILLED** (approval is a valid PERMIT_DATE under the project definition).
- **223** Active/Final rows still lack both Issued and Approved → not repairable from DATA.
- Inactive rows that were previously issued retain upstream PERMIT_DATE; In Review is left without PERMIT_DATE (approved-only fallback restricted to Active/Final).

After: 307 missing. Coverage: Active **50.8%**; Final **89.2%**.  
Flags: **FILLED 69 · FIXED 0**.

### FINAL_DATE

Before: 732 missing (504 of Final); 17 Active rows incorrectly carried `PermitFinaledDate`. Ideal: populated for Final.

- When present, FINAL_DATE already matched `PermitFinaledDate` (**0** mismatches).
- Status repair moved the 17 Active+finaled rows into Final, so those FINAL_DATE values are now appropriate (no clear needed).
- Among Final rows still missing FINAL_DATE, filled from inspections: **10** from approved final-ish types (`FINAL*`, cert of occupancy/completion), **227** from latest other approved inspection (common on simple shutter/plumbing/zoning closes with no `PermitFinaledDate`).
- **274** Final rows remain without FINAL_DATE (empty inspections + blank finaled), including the 7 shells.

After: 495 missing. Coverage: Final **84.6%**; Active/In Review/Inactive **0%**.  
Flags: **FILLED 237 · FIXED 0**.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_coral_springs.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.

## Performance summary

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | -----: | ----: | -------------: | ------------: |
| STATUS_NORMALIZED |      7 |    17 |              7 |             0 |
| FILE_DATE         |      0 |     0 |              9 |             9 |
| PERMIT_DATE       |     69 |     0 |            376 |           307 |
| FINAL_DATE        |    237 |     0 |            732 |           495 |

## Artifacts

- Repaired sample: `AGENT_DATA_PATH/coral_springs_repaired_sample.parquet`
