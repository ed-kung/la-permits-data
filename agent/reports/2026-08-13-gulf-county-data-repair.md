# Gulf County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Gulf County**. DATA is a flat portal scrape (Franklin County–style `simple` keys: `Status` / `Issue Date` / `Work Description`). Upstream left 3 null statuses on column-shifted shells and kept 20 issued permits labeled In Review despite a real `Issue Date`. `FILE_DATE` and `FINAL_DATE` were entirely null; `PERMIT_DATE` already matched parseable `Issue Date` on every Issued/Active row (0 mismatches). The repair filled 3 statuses, fixed 20 In Review→Active, and filled 1,068 `FILE_DATE` values from `Issue Date` (only date field in DATA). After repair: STATUS 100%; Active FILE_DATE / PERMIT_DATE 100%; Final PERMIT_DATE / FINAL_DATE 0% (Closed shells expose no issue/final dates).

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (sorted order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Gulf County, FL** → `agent/scripts/fl/data_repair_fl_gulf_county.py` (1,397 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

Every row is the flat portal scrape. Content suffixes split by whether `Issue Date` parses as a real calendar date (the column often holds work descriptions or names when blank):

| Schema | n | Notes |
| --- | ---: | --- |
| `simple_issued` | 1,068 | Parseable `Issue Date` (1,048 Issued + 20 Under Review) |
| `simple_status_only` | 329 | No parseable issue date (true Under Review, Closed, misaligned) |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status` (fallback `Sub Type` when Status missing/garbage); In Review + parseable Issue Date → Active |
| FILE_DATE | `Issue Date` (fallback only — portal has no applied/submittal field) |
| PERMIT_DATE | `Issue Date` |
| FINAL_DATE | *(none — no Inspections / Finaled stamp)* |

## Field assessments

### STATUS_NORMALIZED

| Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Issued | 1,048 | Active | Correct |
| Under Review | 342 | In Review (20 with real Issue Date) | Fix 20 → Active |
| Closed | 4 | Final | Correct (no dates in DATA) |
| owner name / blank Status | 3 | **null** | Fill → In Review via `Sub Type` |

**Root causes:**
1. Scraping misalignment put applicant names (or left Status blank) while `Sub Type` held `Under Review`.
2. Upstream mapped `STATUS_ORIGINAL = under review` without checking that `Issue Date` already held a real issuance date on 20 shells.

**Repair performance:** FILLED 3, FIXED 20; missing 3 → 0.

Status transitions: In Review→Active 20, null→In Review 3. After: Active 1,068; In Review 325; Final 4.

### FILE_DATE

Ideal: populated for all records.

- Before: missing on **1,397 / 1,397** (100%). DATA has no Apply/Filed/Submitted field.
- Filled from parseable `Issue Date` (same Franklin County simple-schema fallback when Reviews.Start is absent).
- Residual gaps (329): Under Review / Closed / misaligned shells whose `Issue Date` column contains work descriptions, names, or is absent — not a real date.

**Repair performance:** FILLED 1,068, FIXED 0; missing 1,397 → 329 (76.5% overall; **100% on Active**).

### PERMIT_DATE

Ideal: populated for Active and Final.

- Before: missing on **329 / 1,397**. All 1,068 present values matched parseable `Issue Date` (0 calendar mismatches).
- Issued shells already complete; the 20 Under Review→Active upgrades already carried matching `PERMIT_DATE`.
- Final (Closed) shells have no parseable `Issue Date` (column holds site-plan text or is absent) → PERMIT_DATE stays missing (4 / 4).

**Repair performance:** FILLED 0, FIXED 0; missing 329 → 329. Active coverage **1,068 / 1,068 (100%)**; Final **0 / 4**.

### FINAL_DATE

Ideal: populated for Final.

- Before: missing on **1,397 / 1,397**. No Finaled / completion field and no Inspections array in DATA.
- All 4 Final (Closed) rows remain without FINAL_DATE — not repairable from DATA.
- No spurious FINAL_DATE on non-Final statuses.

**Repair performance:** FILLED 0, FIXED 0; Final coverage **0 / 4 (0%)**.

## Repair script performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 20 | 3 → 0 |
| FILE_DATE | 1,068 | 0 | 1,397 → 329 |
| PERMIT_DATE | 0 | 0 | 329 → 329 |
| FINAL_DATE | 0 | 0 | 1,397 → 1,397 |

| Coverage (after) | Rate |
| --- | --- |
| STATUS_NORMALIZED non-null | 1,397 / 1,397 (100%) |
| FILE_DATE | 1,068 / 1,397 (76.5%) |
| FILE_DATE among Active | 1,068 / 1,068 (100%) |
| PERMIT_DATE among Active | 1,068 / 1,068 (100%) |
| PERMIT_DATE among Final | 0 / 4 (0%) |
| FINAL_DATE among Final | 0 / 4 (0%) |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_gulf_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/gulf_county_repaired_sample.parquet`
