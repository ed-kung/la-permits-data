# St. Johns County (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, St. Johns County was first. Its DATA is a Civic/Accela-style portal payload (`Permit Main`, optionally `Project Data` / `Project Holds`). STATUS_NORMALIZED was null on 1,970/2,000 rows because Cert Compl / Cert Occ / Admin Close were never mapped (only Expired/Voided → Inactive). FILE_DATE and PERMIT_DATE were systematically swapped with the wrong portal stamps: FILE_DATE copied `IssueDt` (issuance), and PERMIT_DATE copied `permit_date`/`ComplDt` (completion). FINAL_DATE already matched `ComplDt`. After repair: 1,940 status fills; 1,953 incorrect FILE_DATEs cleared (no application date exists in DATA); PERMIT_DATE corrected to `IssueDt` on 1,953 rows; Final FINAL_DATE coverage 1,645/1,662 (99.0%).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **St. Johns County, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_st_johns_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/st_johns_county_repaired_sample.parquet`

## DATA schema

All records have `Permit Main` + `Charges` + `Associated` + `Inspections`. Variants:

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `portal_full` | 1,858 | + Project Data + Project Holds |
| `portal_basic` | 142 | Permit Main only (no project blocks) |

Content suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_status_only`) reflect which of IssueDt / ComplDt (or equivalent) are populated.

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Permit Main.status` (fallbacks below) |
| FILE_DATE | **none** — no filed/submitted/applied field in DATA |
| PERMIT_DATE | `Permit Main.IssueDt` |
| FINAL_DATE | `Permit Main.ComplDt`, else `permit_date` when ≠ IssueDt, else `Project Holds.CODt` |

`Permit Main.permit_date` mirrors `ComplDt` when both exist; it is **not** an issuance date.

## Field assessments

### STATUS_NORMALIZED

1,970 missing before; only Expired (15) and Voided (15) were mapped to Inactive. **1,940 FILLED + 0 FIXED** (30 missing after):

| Action | Before → After | Portal status / evidence | n |
| --- | --- | --- | ---: |
| FILLED | null → Final | Cert Compl | 1,018 |
| FILLED | null → Final | Cert Occ | 446 |
| FILLED | null → Active | empty status + IssueDt, no ComplDt | 226 |
| FILLED | null → Final | empty status + ComplDt | 199 |
| FILLED | null → Inactive | Admin Close | 52 |
| FILLED | null → Final | empty status + approved BL FNL, no dates | 17 |

Cause: upstream normalization never mapped Cert Compl / Cert Occ / Admin Close, and left blank `Permit Main.status` null even when IssueDt/ComplDt were present. After repair: Final 1,662; Active 226; Inactive 82; null 30 (sparse `portal_basic_status_only` rows with no status, IssueDt, ComplDt, or BL FNL).

### FILE_DATE

Ideal: populated for all records.

- Every non-null FILE_DATE (1,953) equaled `IssueDt` at day resolution — issuance, not application. **0 FILLED / 1,953 FIXED** (cleared).
- DATA has no application / submittal / created stamp (`Notes.Date/User` and hold dates are post-hoc activity, not reliable file dates).
- **2,000 missing after** — not inventable from this payload.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Existing PERMIT_DATE (1,546) equaled `permit_date`/`ComplDt` (completion), never `IssueDt`. **1,546 FIXED** to IssueDt.
- Empty-status issued rows lacked PERMIT_DATE entirely → **407 FILLED** from IssueDt.
- After repair: Active 226/226 (100%); Final 1,645/1,662 (99.0%); Inactive 82/82 (100%).
- Remaining Final gaps: 17 BL FNL-only rows with no IssueDt in DATA.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- When ComplDt present, FINAL_DATE already matched — left as-is.
- **49 FILLED** on Cert Compl rows with blank ComplDt but a distinct `permit_date` completion stamp.
- **78 FIXED** (cleared) on Inactive Admin Close / Expired / Voided that carried a close/completion stamp.
- After repair: Final 1,645/1,662 (99.0%); Active/Inactive 0%.
- Remaining Final gaps: 17 BL FNL-inferred rows with no ComplDt/`permit_date`.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1,940 | 0 | 1,970 → 30 |
| FILE_DATE | 0 | 1,953 | 47 → 2,000 |
| PERMIT_DATE | 407 | 1,546 | 454 → 47 |
| FINAL_DATE | 49 | 78 | 326 → 355 |

## Not repairable from DATA

- FILE_DATE for all rows (no application/submittal field).
- 30 sparse rows with empty status and no IssueDt / ComplDt / BL FNL.
- 17 Final rows inferred only from approved BL FNL inspection (no IssueDt / ComplDt).
