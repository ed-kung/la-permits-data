# Palos Verdes Estates CA data repair

**Summary:** Palos Verdes Estates is the first jurisdiction in `permits_la_sample.parquet` without an existing repair script (La Cañada Flintridge already has `data_repair_ca_la_canada_flintridge.py`). Its 2,000 sample rows are SmartGov portal payloads (`Build Status` + `My Project` dates), same family as Calabasas. Material repairs: fill 464 missing `STATUS_NORMALIZED` values (175 unmapped `Expired:*` labels + 257 null-Build-Status scrapes inferred from dates); fix 21 stale statuses; fill 39 `FILE_DATE`, 31 `PERMIT_DATE`, and 33 `FINAL_DATE` values from `My Project` (plus one Final inspection fallback). After repair, Active and Final rows are 100% covered for `PERMIT_DATE` and Final rows are 100% covered for `FINAL_DATE`. Script: `agent/scripts/data_repair_ca_palos_verdes_estates.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Palos Verdes Estates"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without `data_repair_{state}_{city}.py` | Palos Verdes Estates, CA (La Cañada Flintridge already covered) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `smartgov_full` | 1,681 |
| `smartgov_no_desc` | 163 |
| `smartgov_minimal` | 156 |

Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `Build Status` (fallback: presence of `My Project` Closed / Issued / Submitted|Created) |
| `FILE_DATE` | `My Project.Submitted` (fallback: `Created`) |
| `PERMIT_DATE` | `My Project.Issued` (fallback: `Approved`) |
| `FINAL_DATE` | `My Project.Closed` (fallback: latest approved inspection whose name contains "Final") |

Status map: Closed / Finaled → Final; Issued / Approved → Active; Expired:\* / Cancelled → Inactive; In Review / Pending / Ready To Issue / Complete application/Ready for decision-maker / Open / Returned to applicant for corrections → In Review.

## Field assessment

### STATUS_NORMALIZED — 473 missing; 21 incorrect among present

Upstream mapping covers common labels (Closed→Final, Issued→Active, etc.) but leaves gaps:

1. **`Expired: <date>` not normalized (175 of 551 Expired rows).** Each expiration date is a distinct string, so only earlier Expired values that happened to match a static map were set to Inactive; later ones stayed null.
2. **Null `Build Status` (266 rows).** Recent scrapes omit the status string. Inferring from `My Project` dates recovers 257 (Closed→Final 20, Issued→Active 121, Submitted/Created→In Review 116). Nine rows have an empty `My Project` and remain null.
3. **Other missing Build Status labels (32):** Closed (23), Issued (8), Returned to applicant for corrections (1).

Incorrect present values (21 FIXED) are stale relative to current `Build Status`:

| Change | n | Typical cause |
| --- | --- | --- |
| Active → Final | 7 | Build Status now Closed with a Closed date |
| Active → Inactive | 6 | Build Status now Expired:\* |
| In Review → Active | 4 | Build Status now Issued |
| Inactive → Final | 2 | Build Status Closed (STATUS_ORIGINAL was expired:\*) |
| Inactive → Active | 1 | Build Status Issued |
| In Review → Inactive | 1 | Build Status Expired:\* |

### FILE_DATE — 48 missing; 0 incorrect among present

Where both exist, `FILE_DATE` always matches `My Project.Submitted` (1,952 / 1,952). Of 48 missing, 39 have a usable `Submitted` date → FILLED. Nine empty-payload rows remain missing (same nine with null status).

### PERMIT_DATE — 316 missing overall; 0 incorrect among present

Where both exist, `PERMIT_DATE` always matches `My Project.Issued` (1,684 / 1,684). Gaps are mostly non-Active/Final rows (expected). After status repair, 31 Active/Final rows gain a date (28 from Issued, 3 from Approved when Issued is blank). Post-repair coverage: Active 266/266, Final 946/946.

### FINAL_DATE — mostly correct for Final; 1 fillable Final gap

Where both exist, `FINAL_DATE` always matches `My Project.Closed` (920 / 920). After status repair, 32 Final rows fill from Closed, and 1 `Finaled` row with blank Closed fills from an approved "Public Works Final" inspection (2023-06-22). Post-repair: Final 946/946 (100%). Seven Inactive (Expired) rows retain a Closed-derived `FINAL_DATE` already present upstream; left as-is (same convention as Calabasas).

## Repair performance

| Field | Missing before | FILLED | FIXED | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 473 | 464 | 21 | 9 |
| FILE_DATE | 48 | 39 | 0 | 9 |
| PERMIT_DATE | 316 | 31 | 0 | 285 |
| FINAL_DATE | 1,080 | 33 | 0 | 1,047 |

STATUS_NORMALIZED distribution:

| Status | Before | After |
| --- | --- | --- |
| Final | 894 | 946 |
| Inactive | 373 | 552 |
| Active | 145 | 266 |
| In Review | 115 | 227 |
| NaN | 473 | 9 |

Post-repair date coverage by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 266 / 266 (100%) | 0 / 266 (0%) |
| Final | 946 / 946 (100%) | 946 / 946 (100%) |
| In Review | 7 / 227 (3.1%) | 0 / 227 (0%) |
| Inactive | 496 / 552 (89.9%) | 7 / 552 (1.3%) |

FILE_DATE after repair: 1,991 / 2,000 (99.6%).

## Not repairable

- Nine records with empty `My Project` and null `Build Status` / `Permit Type` — no status or dates in DATA.
- Remaining missing `PERMIT_DATE` / `FINAL_DATE` are almost entirely In Review or Inactive rows, where those fields are not required.

## Artifacts

- Script: `agent/scripts/data_repair_ca_palos_verdes_estates.py` (`data_repair`)
- Report: `agent/reports/2026-07-24-palos-verdes-estates-data-repair.md`
