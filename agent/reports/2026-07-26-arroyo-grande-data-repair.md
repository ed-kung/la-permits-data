# Arroyo Grande (CA) data repair

**Summary:** Arroyo Grande was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from a flat CityView-style `DATA` JSON. Status missingness fell from **373 → 21** (**FILLED 352 · FIXED 1**): unmapped numbered workflow statuses (Under Review / Plan Approved / Being Constructed / Project Complete), Pending - See Notes, and shifted scrapes whose real status sat in `Sub Type` were filled; one `Test` row was corrected from In Review → Inactive. `PERMIT_DATE` already matched parseable `Issue Date` for all 1,504 overlapping rows; **FILLED 6** additional Active dates recovered from shifted rows where the issue date was stored in `Status`. `FILE_DATE` and `FINAL_DATE` remain null for all 2,000 rows — DATA has no application or completion date fields.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Arroyo Grande, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_arroyo_grande.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are flat CityView portal scrapes with keys `Status`, `Address `, `Permit #`, `Sub Type`, `Permit Type`, optional `Issue Date` / `Work Description`. Variants reflect scrape quality:

| Schema | n | Description |
| --- | ---: | --- |
| `cityview_standard` | 1,567 | Canonical `Status`; `Issue Date` is a date or absent |
| `cityview_desc_in_issue` | 401 | Canonical `Status`; `Issue Date` holds work-description text |
| `cityview_no_status` | 15 | `Status` key missing / empty |
| `cityview_shifted` | 11 | Real status in `Sub Type`; `Status` is a date or description |
| `cityview_garbled` | 6 | Non-canonical `Status` and no recoverable status in `Sub Type` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.Status`; else `Sub Type` when shifted; else VOID detected in Status text |
| `FILE_DATE` | *(none in DATA)* |
| `PERMIT_DATE` | `Issue Date` when parseable; else `Status` when Status is `MM/DD/YYYY` on shifted rows |
| `FINAL_DATE` | *(none in DATA)* |

## Findings by field

### STATUS_NORMALIZED

**Before:** Active 694 · Final 583 · In Review 100 · Inactive 250 · null 373.

Upstream mapped common labels (`Issued`, `Finaled`, `Expired`, `Withdrawn`, `Void`, `Closed`, `Approved`, `3. Permit Issued`, `Under Review`, `Out for Corrections`, `Online Application Received`) correctly, but left null:

| Raw `Status` / recovered | n | Mapped to |
| --- | ---: | --- |
| `2. Plan Approved` | 167 | Active |
| `7. Project Complete` | 97 | Final |
| `1. Under Review` | 60 | In Review |
| `Pending - See Notes` | 14 | In Review |
| `4. Being Constructed` | 4 | Active |
| Shifted (`Sub Type` = status) | 10 null + 1 already Inactive | per Sub Type map |

**Incorrect value:** `Test` was normalized to In Review → FIXED to Inactive.

**After:** Active 871 · Final 681 · In Review 174 · Inactive 253 · null 21 (15 no-status + 6 garbled free-text Status values with no recoverable alternative).

### FILE_DATE

Null for **all 2,000** rows. DATA has no application / submittal / applied date. No fills or fixes possible.

### PERMIT_DATE

Where both present, `PERMIT_DATE` matched `Issue Date` exactly (1,504 / 1,504). Missingness is driven by missing or non-date `Issue Date` (often work description text in the Issue Date slot).

| Change | n |
| --- | ---: |
| FILLED (shifted Status date → Active) | 6 |
| FIXED | 0 |
| Missing before → after | 496 → 490 |

After repair, Active has PERMIT_DATE for **765 / 871 (87.8%)** and Final for **616 / 681 (90.5%)**. Remaining Active/Final gaps are mostly `cityview_desc_in_issue` (Approved / Closed / Plan Approved with description text in Issue Date) or true missing Issue Date — not recoverable from DATA.

### FINAL_DATE

Null for **all 2,000** rows, including 681 Final records (`Finaled`, `Closed`, `7. Project Complete`). DATA exposes completion only as Status text, never as a date. No fills or fixes possible.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| `STATUS_NORMALIZED` | 352 | 1 | 373 | 21 |
| `FILE_DATE` | 0 | 0 | 2,000 | 2,000 |
| `PERMIT_DATE` | 6 | 0 | 496 | 490 |
| `FINAL_DATE` | 0 | 0 | 2,000 | 2,000 |

## Not repairable / left as-is

- All `FILE_DATE` and `FINAL_DATE` values (no source fields in DATA).
- ~106 Active and ~65 Final rows still missing `PERMIT_DATE` (no parseable Issue Date).
- 21 rows with missing/garbled Status and no recoverable Sub Type status.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_arroyo_grande.py`
- This report: `agent/reports/2026-07-26-arroyo-grande-data-repair.md`
