# Houston (TX) Data Repair Assessment

## Summary

Houston, TX was the first `(JURISDICTION, STATE)` pair in `permits_top50_sample.parquet` lacking a `data_repair_{state}_{city}.py` script. Assessed 2,001 sample records against the raw `DATA` JSON. Houston’s scrape is sparse: no status field, no application/filing date, and no completion date. **STATUS_NORMALIZED is already correct** (all Active / `issued`). **FILE_DATE and FINAL_DATE cannot be recovered** from `DATA`. **PERMIT_DATE** can be fully completed: 25 missing values filled and 17 stale renewal dates fixed using `details.Date` (with top-level `date` as a fill-only fallback for empty-details stubs). Repair script: `agent/scripts/data_repair_tx_houston.py`.

## Baseline (sample, n=2,001)

| Field | Missing | Present | Notes |
|-------|---------|---------|-------|
| STATUS_NORMALIZED | 0 (0%) | 2,001 | All `Active` |
| STATUS_ORIGINAL | 0 | 2,001 | All `issued` |
| FILE_DATE | 2,001 (100%) | 0 | |
| PERMIT_DATE | 25 (1.2%) | 1,976 | |
| FINAL_DATE | 2,001 (100%) | 0 | |

## DATA structure

Two top-level key-set schemas (recorded as `INFERRED_SCHEMA`):

| Schema | Count | Keys |
|--------|------:|------|
| `details_search` | 1,745 | `details`, `search` |
| `date_details_search` | 256 | `date`, `details`, `search` |

`details` is a flat dict (`Address`, `Buyer`, `Date`, `FCC Group`, `Job Address`, `Owner/Occupant`, `Permit Type`, `Phone`, `Project No`, `USE`, `Valuation`) on 1,971 rows and an **empty dict** on 30 rows. `search` is always a list of display tokens (project no, record type, owner, address, use, valuation, permit type code). There is **no status, filed, issued, final, or completion key** beyond `details.Date` and the optional top-level `date`.

## Field assessments

### STATUS_NORMALIZED — correct; nothing to repair

- Every row is `STATUS_ORIGINAL == "issued"` → `STATUS_NORMALIZED == "Active"`.
- `DATA` contains no status / phase / milestone field to contradict or refine this.
- Certificate-of-occupancy and compliance record types (`CERT OF OCCUP.`, `CRT/COMPLIANCE`) are separate issued records, not evidence that building permits should be reclassified to `Final`.
- **FILLED: 0, FIXED: 0.**

### FILE_DATE — not recoverable

- No application, submitted, filed, or pre-filing date exists in `DATA`.
- `details.Date` matches existing `PERMIT_DATE` on **1,954 / 1,971 (99.1%)** of rows that have both → it is an **issuance** date, not a filing date.
- Top-level `date` (256 rows, 12.8%) often equals `details.Date` (165/226 overlaps) and otherwise scatters around it (especially on renewals). It is not a reliable filing date.
- **FILLED: 0, FIXED: 0.** Missing remains 2,001.

### PERMIT_DATE — fillable and partially incorrect

**Canonical source:** `details.Date`.

| Issue | Count | Action |
|-------|------:|--------|
| Missing `PERMIT_DATE`, empty `details`, top-level `date` present | 25 | **FILLED** from top-level `date` |
| `PERMIT_DATE` ≠ `details.Date` (mostly Sign / Elevator renewals; ~1-year offsets) | 17 | **FIXED** to `details.Date` |
| Empty `details` with an existing `PERMIT_DATE` that disagrees with top-level `date` | 5 | **left as-is** (top date too weak to overwrite) |

After repair: **0 missing**; among rows with `details.Date`, agreement is **1,971 / 1,971 (100%)**.

### FINAL_DATE — not recoverable

- No completion, final, sign-off, or COO date field in `DATA`.
- No row has (or can be justified as) `STATUS_NORMALIZED == Final`, so `FINAL_DATE` is not expected under the project rules either.
- **FILLED: 0, FIXED: 0.** Missing remains 2,001.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
|-------|-------:|------:|---------------:|--------------:|
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 2,001 | 2,001 |
| PERMIT_DATE | 25 | 17 | 25 | 0 |
| FINAL_DATE | 0 | 0 | 2,001 | 2,001 |

Post-repair coverage by status (all rows remain Active):

- `PERMIT_DATE`: 2,001 / 2,001 (100%)
- `FILE_DATE`: 0 / 2,001 (0%)
- `FINAL_DATE`: 0 / 2,001 (0%)

## Artifacts

| Path | Description |
|------|-------------|
| `agent/scripts/data_repair_tx_houston.py` | `data_repair(df)` implementation |
| `$AGENT_DATA_PATH/houston_repaired_sample.parquet` | Repaired sample with flag + `INFERRED_SCHEMA` columns |
