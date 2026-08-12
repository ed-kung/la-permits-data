# Hialeah (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Hialeah**. DATA is a flat city-portal project payload (`Status`, `Reviews`, `Inspections`) with one key set and content variants by which date collections are populated. `STATUS_NORMALIZED` was null for 189 rows (mainly `RO Issued`) and lagged live `Status` on 2 rows — all repaired. `FILE_DATE` was entirely missing and was filled for 1,921 / 1,999 rows from earliest review/inspection `Date Created`. `PERMIT_DATE` was filled for 570 rows and fixed on 104 rows where upstream used a non-earliest inspection date. No finaled/sign-off timestamp exists in DATA, so `FINAL_DATE` remains fully missing. After repair: STATUS 100% populated; FILE_DATE 96.1%; Active/Final PERMIT_DATE 82.1–82.8%; Final FINAL_DATE 0%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Hialeah, FL** → `agent/scripts/fl/data_repair_fl_hialeah.py` (1,999 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `hialeah_rev_insp` | 1,557 | Usable dates in both `Reviews` and `Inspections` |
| `hialeah_rev_only` | 364 | Review dates only (inspections empty or blank `Date Created`) |
| `hialeah_status_only` | 78 | No usable review or inspection dates |

All rows share the same top-level keys. Nested `Reviews[]` fields: `Date Created`, `Date Reviewed`, `Review Status`, etc. Nested `Inspections[]` fields: `Date Created`, `Permit Status`, `Permit Type`, etc. — **no** issue date, finaled date, or CO date field.

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status` |
| FILE_DATE | Earliest `Reviews[].Date Created` or `Inspections[].Date Created` |
| PERMIT_DATE | Earliest `Inspections[].Date Created` (issuance proxy) |
| FINAL_DATE | *(none)* |

## Field assessments

### STATUS_NORMALIZED

| DATA.Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Finaled | 983 | Final (981); Active/Inactive lag (2) | Fix 2 lags |
| Closed | 371 | Final | Correct |
| RO Issued | 181 | **null** | Fill → Final (re-occupancy certificate) |
| Renewed | 85 | Active | Correct |
| Active | 81 | Active | Correct |
| Expired | 80 | Inactive | Correct |
| Void | 49 | Inactive | Correct |
| CO Issued | 44 | Final | Correct |
| Canceled | 37 | Inactive | Correct |
| Abandoned | 31 | Inactive | Correct |
| On Review | 18 | In Review | Correct |
| CC Issued | 16 | Final | Correct |
| Plans Pick-Up | 5 | **null** | Fill → In Review |
| Hold / Open / Ready / Lien | 11 | In Review | Correct |
| RO Conditional | 3 | **null** | Fill → Active |
| Denied / Duplicate | 4 | Inactive | Correct |

**Root cause of nulls:** upstream mapper did not cover `RO Issued`, `Plans Pick-Up`, or `RO Conditional`. Two rows had `STATUS_ORIGINAL` lagging live `Status` (`active`/`expired` vs `Finaled`).

**Repair performance:** FILLED 189, FIXED 2; missing 189 → 0.

### FILE_DATE

- Before: missing on **all 1,999** rows.
- Source: earliest `Date Created` across Reviews and Inspections (application/submittal proxy; keeps `FILE_DATE ≤ PERMIT_DATE` when both exist).
- After: missing on **78** rows (`hialeah_status_only` — empty Reviews/Inspections or blank dates only). No year-only fallback from `Project Number`.

**Repair performance:** FILLED 1,921, FIXED 0; missing 1,999 → 78 (96.1% coverage).

### PERMIT_DATE

- Before: missing on **1,016 / 1,999** rows; present values always matched *some* `Inspections[].Date Created`, but 104 used a non-earliest list item rather than the chronological minimum.
- After fill/fix for Active/Final/Inactive when an inspection date exists.
- Remaining Active/Final gaps (314): almost all `hialeah_rev_only` or `hialeah_status_only` — no inspection `Date Created` to use as issuance proxy (common for `Closed` / `RO Issued` shells).

**Repair performance:** FILLED 570, FIXED 104; missing 1,016 → 446. Active coverage 82.8%; Final coverage 82.1%.

### FINAL_DATE

- Before: missing on **all 1,999** rows, including every Final record.
- Inspections only store creation dates of trade permits; Reviews only store plan-review dates. No finaled / CO / sign-off timestamp is present.

**Repair performance:** FILLED 0, FIXED 0; missing 1,999 → 1,999. Final coverage: 0%.

## Ideal-field checklist (after repair)

| Rule | Result |
| --- | --- |
| FILE_DATE populated for all records | Mostly (96.1%; 78 lack any date-bearing nested rows) |
| PERMIT_DATE for Active and Final | Partial (~82%; remainder have no inspection dates) |
| FINAL_DATE for Final | No (0% — not in DATA) |

Status distribution after repair: Final 1,595; Inactive 201; Active 169; In Review 34.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_hialeah.py`
- Repaired sample: `$AGENT_DATA_PATH/hialeah_repaired_sample.parquet`
