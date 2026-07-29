# Marin County (CA) data repair

**Summary:** Marin County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows are a flat issued-permits feed (`received_date` / `issued_date`) with null `STATUS_ORIGINAL` and null `STATUS_NORMALIZED`. Repair fills every status to **Active** from `issued_date` (**2,000 FILLED**) and fills **411** missing `FILE_DATE` values from `received_date`. `PERMIT_DATE` already matched `issued_date` on every row; `FINAL_DATE` cannot be recovered (no completion field). After repair: FILE_DATE 100%, Active PERMIT_DATE 100%, no Final rows.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Marin County, CA** (index 215, after Pittsburg / Healdsburg batch).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Keys |
| --- | ---: | --- |
| `flat_received_issued` | 2,000 | address, city_town, construction, construction_value, contractor, description, issued_date, most_recent_issued_received_date, parcel_number, permit_category, received_date, type_permit |

Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | (no status key) — infer Active when `issued_date` present |
| `FILE_DATE` | `received_date` |
| `PERMIT_DATE` | `issued_date` (sample: identical to `most_recent_issued_received_date`) |
| `FINAL_DATE` | (none) |

`type_permit` is mostly RESIDENTIAL (1,887) / COMMERCIAL (113). `permit_category` is Maintenance / All other Construction / Minor Improvement. No CaseStatus, PermitStatus, or finaled/completion key appears on any row.

## Field assessment

### STATUS_NORMALIZED

Before: **2,000 / 2,000 missing**. `STATUS_ORIGINAL` is also entirely null.

This feed is an issued-permits listing only. Every row has a parseable `issued_date` (2022-04-18 … 2025-08-01). Following the blank-shell + issuance-stamp convention (Costa Mesa flat list / Union City / Newark), all rows are filled to **Active**.

No rows can be labeled Final / In Review / Inactive without a terminal status, review-stage status, or finaling stamp in DATA. Rows with only `received_date` (none in sample) would map to In Review.

Repair: **2,000 FILLED, 0 FIXED**; missing after: **0**. After: Active 2,000.

### FILE_DATE

Before: **411 / 2,000 missing** (mostly older received years: 390 in 2022, plus 21 in 2019–2021).

- `received_date` is present on every row.
- Where both present (1,589), `FILE_DATE` already matches `received_date` at calendar-day resolution (0 mismatches).
- Missingness does not track midnight vs timed stamps, or same-day vs delayed issuance; it is primarily an upstream gap for earlier vintages.

Repair: **411 FILLED, 0 FIXED**. Coverage after: **2,000 / 2,000 (100%)**.

### PERMIT_DATE

Before: **0 missing**. Every row matches `issued_date` (and `most_recent_issued_received_date`, which equals `issued_date` on all 2,000 rows) at calendar-day resolution.

After status fill to Active, ideal Active/Final coverage is already 100%. No fills or fixes.

Repair: **0 FILLED, 0 FIXED**.

### FINAL_DATE

Before: **2,000 / 2,000 missing**. No finaled / completion / signoff field exists in DATA. No rows are classified as Final after repair, so the ideal Final/`FINAL_DATE` coverage target does not apply. No spurious FINAL_DATE values were present to clear.

Repair: **0 FILLED, 0 FIXED**.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_marin_county.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_marin_county_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2,000 | 0 | 2,000 → 0 |
| FILE_DATE | 411 | 0 | 411 → 0 |
| PERMIT_DATE | 0 | 0 | 0 → 0 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Status after: Active 2,000.

Status transitions: nan → Active 2,000.

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 2,000 / 2,000 (100%); Final n/a
- FINAL_DATE: Final n/a; non-Final with FINAL_DATE: 0
- Chronology inversions: FILE > PERMIT 0; PERMIT > FINAL 0

Ideal-coverage gaps that cannot be closed without a richer agency feed: any Final / Inactive / In Review labeling, and all `FINAL_DATE` values.
