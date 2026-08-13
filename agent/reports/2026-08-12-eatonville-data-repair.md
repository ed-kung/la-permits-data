# Eatonville (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Eatonville**. DATA is a municipal portal form payload (`Status:`, `Permit #:`, `Permit Details`, `Inspections`, `Reviews`; top-level `Issue Date` always null). Upstream left 38 `STATUS_NORMALIZED` nulls when `Status:` was blank, mislabeled one Issued row as Final via stale `STATUS_ORIGINAL=closed`, and left 27 pre-issuance shells as In Review despite a `Permit Details` Issue Date. `FILE_DATE` and `FINAL_DATE` were null for every row; DATA has no application/submittal date, so FILE_DATE is unrepairable. Present `PERMIT_DATE` already matched Issue Date exactly (205/205). The repair filled 38 statuses and fixed 28, filled 5 `FINAL_DATE` values from passed Final* inspections, and left PERMIT_DATE/FILE_DATE unchanged (0 fills/fixes). After repair: STATUS 100%; FILE_DATE 0%; Active/Final PERMIT_DATE 81.2%/45.2%; Final FINAL_DATE 11.9%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Eatonville, FL** → `agent/scripts/fl/data_repair_fl_eatonville.py` (484 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

Almost all rows share portal keys `Status:`, `Permit #:`, `Project #:`, `Permit Type`, `Permit Details`, `Inspections`, `Reviews`, `Issue Date`, `Address:`, `Description:`. Variants differ by how much of the building-permit form was scraped:

| Schema | n | Notes |
| --- | ---: | --- |
| `portal_full_applied` | 247 | Full form; no Issue Date / Final* insp |
| `portal_full_issued` | 166 | Full form + Issue Date |
| `portal_partial_applied` | 30 | Valuation form, missing some contractor docs |
| `portal_partial_issued` | 27 | Partial + Issue Date |
| `portal_full_issued_finaled` | 6 | Issue Date + passed Final* inspection |
| `portal_minimal_issued` | 5 | Core keys only + Issue Date |
| `portal_minimal_applied` | 2 | Core keys only |
| `portal_partial_issued_finaled` | 1 | Partial + issued + finaled |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `DATA["Status:"]`; In Review upgraded to Active when Issue Date exists; blank status inferred from Issue Date / Final* inspections |
| FILE_DATE | **None** (no application/received/submittal field) |
| PERMIT_DATE | `Permit Details["Issue Date:"]` |
| FINAL_DATE | Latest passed (or blank-status dated) Final* inspection |

## Field assessments

### STATUS_NORMALIZED

| DATA `Status:` | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Processing | 191 | In Review (26 have Issue Date) | Keep In Review; upgrade Issue Date rows → Active |
| Issued | 135 | Active (1 Final) | Fix Final → Active |
| Approved | 61 | Active | Correct (18 have Issue Date) |
| Closed | 41 | Final | Correct |
| *(blank)* | 38 | **null** | Fill: Active if Issue Date (6), Final if Final* insp (1), else In Review (31) |
| More Information Needed | 15 | In Review (1 has Issue Date) | Upgrade Issue Date row → Active |
| Online Application Received | 3 | In Review | Correct |

**Root causes:**
1. Blank `Status:` left both `STATUS_ORIGINAL` and `STATUS_NORMALIZED` null (scrape/portal gap).
2. One Issued row kept `STATUS_ORIGINAL=closed` / `STATUS_NORMALIZED=Final` while `DATA["Status:"]` is Issued.
3. Portal status often lags issuance: Processing / More Information Needed shells can already carry `Permit Details` Issue Date.

**Repair performance:** FILLED 38, FIXED 28; missing 38 → 0.

### FILE_DATE

- Before: missing on **484 / 484**.
- Date-like values in DATA appear only under `Permit Details.Issue Date:` (205), `Permit Details.Expiration Date:` (41), and `Inspections[].Date` (26). No application / received / filed / submitted stamp exists.
- Ideal coverage cannot be improved from DATA alone.

**Repair performance:** FILLED 0, FIXED 0; missing 484 → 484 (0% coverage).

### PERMIT_DATE

- Before: NaN on **279 / 484**. All 205 present values matched `Permit Details["Issue Date:"]` at calendar-day resolution (0 mismatches). Top-level `Issue Date` is always null.
- No missing Issue Date was left unmapped upstream → 0 FILLED.
- After status repair, Active coverage is 186 / 229 (81.2%); gaps are mostly `Approved` without Issue Date (43) plus a few upgraded empty-status Active shells that also lack Issue Date.
- Final coverage is 19 / 42 (45.2%): 23 `Closed` shells never recorded an Issue Date.
- Remaining In Review rows correctly have 0% PERMIT_DATE after Issue-date upgrades.

**Repair performance:** FILLED 0, FIXED 0; missing 279 → 279. Active 81.2%; Final 45.2%; In Review 0%.

### FINAL_DATE

- Before: NaN on **484 / 484**; Final had 0 / 42 present.
- Only 17 rows have any inspections; 5 Closed/inferred-Final rows carry a usable Final* completion date (`R - Roof Final` with Passed or blank status + real calendar date). Scheduled / Online Inspection Requested dates are ignored.
- 37 Closed shells still lack a Final* inspection → FINAL_DATE stays missing.
- Non-Final rows with Final* inspections (Issued/Approved) keep status from `Status:` and do not receive FINAL_DATE.

**Repair performance:** FILLED 5, FIXED 0; missing 484 → 479. Final coverage 5 / 42 (11.9%).

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_eatonville.py`
- Entry point: `data_repair(df)`
- Outputs: overwritten `STATUS_NORMALIZED` / `FILE_DATE` / `PERMIT_DATE` / `FINAL_DATE`; flags `*_FLAG` (`FILLED` / `FIXED`); `INFERRED_SCHEMA`
- CLI: `python agent/scripts/fl/data_repair_fl_eatonville.py` prints before/after coverage stats
