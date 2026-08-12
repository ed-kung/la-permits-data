# Columbia County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Columbia County**. DATA is a flat county-portal payload (`Status` / `Submitted` / `Issued` / `Completed` / `Review` / `Inspection`). Upstream left 451 statuses null (mostly blank `Status` with an `Issued` date, plus review-stage labels), mislabeled 20 Completed rows, and left 110 `FILE_DATE` blanks where `Submitted` was empty despite Review timestamps. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 98.9%; Final FINAL_DATE 100%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py` (slug via `[^a-z0-9]+` → `_`). First missing: **Columbia County, FL** → `agent/scripts/fl/data_repair_fl_columbia_county.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `portal_geo_completed` | 1,367 | Has `Completed`; includes street/city/zip |
| `portal_geo_issued` | 552 | Has `Issued`, no `Completed` |
| `portal_geo_submitted` | 80 | Has `Submitted` only (no Issued/Completed) |
| `portal_base_submitted` | 1 | Same permit fields; no street/city/zip |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status`; blank Status inferred from Issued/Completed |
| FILE_DATE | `Submitted`; else earliest Review key date; else earliest Inspection `Date`; else `Issued` |
| PERMIT_DATE | `Issued` when not a post-completion reissue; else Review note announcing issuance |
| FINAL_DATE | `Completed` (Final rows only) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,350; null 451; Active 192; In Review 7.

Root causes of nulls / errors:

- **366** rows with blank `Status` but populated `Issued` (legacy extracts) were left null → should be **Active**.
- Many review-stage labels (`Final Review - *`, `Point Review - *`, `Pending *`, etc.) were unmapped → **In Review** (or **Active** when `Issued` is set, e.g. all 23 `Final Review - Complete`).
- **18** rows with DATA `Status=Completed` still carried upstream `STATUS_ORIGINAL=permit issued` / `STATUS_NORMALIZED=Active` (stale) → **FIXED** to Final.
- A few `Permit Issued` / review rows were mislabeled Final or In Review → **FIXED**.

| Portal signal | Expected | Notes |
| --- | --- | --- |
| `Completed` | Final | Includes stale Active overrides |
| `Permit Issued` / reissue strings | Active | |
| `Final Review - Complete` | Active | All have `Issued` in sample |
| Other named workflow labels | Active if `Issued`, else In Review | |
| Blank Status + Issued | Active | |
| Blank Status, no Issued | In Review | |

**Repair performance:** FILLED 451, FIXED 39; missing 451 → 0.

After: Final 1,367; Active 552; In Review 81.

### FILE_DATE

- Before: missing on **110 / 2,000** rows.
- When both present, `FILE_DATE` already matched `Submitted` on all 1,890 rows (0 mismatches).
- The 110 blanks all have empty `Submitted` but Review key dates (108) or Inspection dates (2) → **FILLED**.
- Using `Issued` as last-resort fallback is implemented but unused in this sample.

**Repair performance:** FILLED 110, FIXED 0; missing 110 → 0 (100% coverage).

### PERMIT_DATE

- Before: missing on **88** rows; 1,894 of 1,897 non-empty `Issued` values already matched `PERMIT_DATE`.
- **3** mismatches vs `Issued`: two reissue rows (PERMIT later than Issued) → **FIXED** to Issued; one Completed row where `Issued` is a **2024 reissue after 2018 completion** → Issued ignored so original PERMIT retained.
- **15** unissued review-stage rows carried spurious `PERMIT_DATE` with empty `Issued` → status → In Review and PERMIT **cleared**.
- **22** Final (`Completed`) rows have empty `Issued` and no issuance Review note → cannot fill (98.4% of Final; 98.9% of Active+Final).

**Repair performance:** FILLED 0, FIXED 18 (15 clears + 3 date corrections); missing 88 → 103 (net increase from clearing spurious In Review stamps). Active coverage 100%; Final 98.4%.

### FINAL_DATE

- Before: missing on **650** rows; all 1,350 upstream Final rows already had FINAL_DATE matching `Completed`.
- **20** Completed rows mislabeled Active/null had `Completed` in DATA but null FINAL → status Fixed/Filled to Final and FINAL **FILLED**.
- **3** non-Completed rows had spurious FINAL (2 `Permit Issued`, 1 pending) → status corrected and FINAL **cleared**.

**Repair performance:** FILLED 20, FIXED 3; missing 650 → 633. Final coverage 100%; non-Final FINAL_DATE 0%.

## Ideal-field checklist (after repair)

| Rule | Result |
| --- | --- |
| FILE_DATE populated for all records | Yes (100%) |
| PERMIT_DATE for Active and Final | Mostly (1,897 / 1,919 = 98.9%; 22 Final lack Issued) |
| FINAL_DATE for Final | Yes (100%) |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_columbia_county.py`
- Repaired sample: `$AGENT_DATA_PATH/columbia_county_repaired_sample.parquet`
