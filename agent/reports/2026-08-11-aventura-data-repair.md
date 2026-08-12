# Aventura (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Alachua County … Auburndale and other already-scripted cities in list order) was **Aventura**. DATA is Accela-style JSON (`permit_info` / `search_data` / `inspections`). STATUS_NORMALIZED already matched `PermitStatus` on every non-shell row; 10 empty shells remain unmapped. FILE_DATE was filled on those 10 shells from `search_data.Application`. PERMIT_DATE could not be improved (Issued/Approved blank on almost all Final CONV rows; fee paid dates are not a safe proxy). FINAL_DATE gained 133 fills from approved final inspections on Final rows that lacked `PermitFinaledDate` (mostly CO/CC).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered jurisdictions through Auburndale (plus other later cities already scripted). **Aventura** was the first without `agent/scripts/fl/data_repair_fl_aventura.py`.

Sample size: **2,000** records.

## DATA schemas

All rows share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Content variants by which `permit_info` dates are populated:

| INFERRED_SCHEMA         | Count |
| ----------------------- | ----: |
| `accela_finaled`        | 1,651 |
| `accela_issued`         |   151 |
| `accela_applied`        |   144 |
| `accela_issued_finaled` |    44 |
| `accela_shell`          |    10 |

Canonical source fields:

| Target field      | DATA source                                                          |
| ----------------- | -------------------------------------------------------------------- |
| STATUS_NORMALIZED | `permit_info.PermitStatus`                                           |
| FILE_DATE         | `PermitAppliedDate`, else `search_data.Application`                  |
| PERMIT_DATE       | `PermitIssuedDate`, else `search_data.Issued`, else `PermitApprovedDate` (Active/Final) |
| FINAL_DATE        | `PermitFinaledDate`, else latest approved final-ish / any inspection |

## Field assessments

### STATUS_NORMALIZED

Before/after: Final 1,831 · Active 139 · In Review 18 · Inactive 2 · missing 10.

- Non-null mappings already matched `PermitStatus` 1:1 (`FINALED` / `CERTIFICATE OF OCCUPANCY` / `CERTIFICATE OF COMPLETION`→Final; `APPROVED`→Active; `ON HOLD` / `IN PLAN CHECK`→In Review; `CANCELLED` / `EXPIRED`→Inactive).
- **10** `accela_shell` rows have blank `PermitStatus`, empty dates in `permit_info`, empty `site_info` / fees / inspections, and only `search_data` (Application + Permit Number). No status signal → left missing.

Flags: **FILLED 0 · FIXED 0**.

### FILE_DATE

Before: 10 missing. Ideal: populated for all records.

- Upstream FILE_DATE matched `PermitAppliedDate` on all 1,990 non-shell rows (**0** day mismatches); also matched `search_data.Application` on those rows.
- **10** shells had blank `PermitAppliedDate` but a usable `search_data.Application` → **FILLED**.

After: 0 missing. Coverage: Active/Final/In Review/Inactive **100%** (shells still lack STATUS_NORMALIZED but now have FILE_DATE).  
Flags: **FILLED 10 · FIXED 0**.

### PERMIT_DATE

Before/after: **1,805 missing**. Ideal: populated for Active and Final.

- When present (195 rows), PERMIT_DATE already matched `PermitIssuedDate`, `PermitApprovedDate`, and `search_data.Issued` (**0** mismatches). Active coverage was already **100%**; Inactive also had Issued.
- **1,777** Active/Final rows still lack Issued and Approved (1,652 `finaled` + 97 CO + 28 CC). `search_data.Issued` is also blank on these CONV-legacy rows.
- Investigated `fees.fees[*].Paid Date` for “PERMIT FEES” as a proxy: of 79 rows with both Issued and a permit-fee paid date, only **1** matched exactly (median offset 7 days; outliers hundreds of days) → rejected.

Flags: **FILLED 0 · FIXED 0**. Not further repairable from DATA. Coverage after: Active **100%**; Final **2.9%**.

### FINAL_DATE

Before: 305 missing (136 of Final). Ideal: populated for Final.

- When present, FINAL_DATE already matched `PermitFinaledDate` (**0** mismatches). Note: 400 rows share finaled date `2005-05-27` in source DATA (bulk CONV closeout); left as-is.
- Among Final rows still missing FINAL_DATE: **133** filled from latest approved final-ish inspection (`*FINAL*`, certificate patterns). Breakdown of fills: CO 97, CC 27, finaled 9.
- **3** Final rows remain without FINAL_DATE (blank `PermitFinaledDate` and no approved inspections).
- No non-Final rows incorrectly carried FINAL_DATE.

After: 172 missing overall; Final coverage **99.8%** (1,828 / 1,831).  
Flags: **FILLED 133 · FIXED 0**.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_aventura.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.

## Performance summary

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | -----: | ----: | -------------: | ------------: |
| STATUS_NORMALIZED |      0 |     0 |             10 |            10 |
| FILE_DATE         |     10 |     0 |             10 |             0 |
| PERMIT_DATE       |      0 |     0 |          1,805 |         1,805 |
| FINAL_DATE        |    133 |     0 |            305 |           172 |

## Artifacts

- Repaired sample: `AGENT_DATA_PATH/aventura_repaired_sample.parquet`
