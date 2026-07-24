# Los Angeles CA data repair

**Summary:** Los Angeles is the first (JURISDICTION, STATE) pair in the LA sample without an existing repair script (after Long Beach). Its 2,002 sample rows use a flat LADBS permit-detail payload with two sub-schemas: `ladbs` (1,881 rows with dated status history) and `ladbs_no_history` (121 rows whose history is only `No Data Available.`). Upstream left `STATUS_NORMALIZED` null on all no-history rows, misclassified 57 statuses where Current Status lagged terminal history (or vice versa), left `FILE_DATE` empty on 1,401 rows (mostly internet permits that never recorded a Submitted event), and missed `FINAL_DATE` on Closed / CofC / Completed finals while leaving a few spurious finals on non-Final rows. The repair fills or fixes all statuses, fills 1,327 file dates, fills 10 permit dates, fills 122 final dates, and clears 6 spurious finals. After repair, every Final row has `FINAL_DATE`, and every Active row has both `FILE_DATE` and `PERMIT_DATE`. Script: `agent/scripts/data_repair_ca_los_angeles.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Los Angeles"`, `STATE == "CA"` |
| N | 2,002 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Los Angeles, CA |

| INFERRED_SCHEMA | n | Description |
| --- | --- | --- |
| `ladbs` | 1,881 | `Permit Application Status History` has dated workflow events |
| `ladbs_no_history` | 121 | History is `[['No Data Available.']]`; only `Current Status` is usable |

Optional keys `Issuing Office` (1,708) and `Certificate of Occupancy` (179) appear on some rows but do not change repair logic.

Canonical fields in DATA:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `Current Status` token + last meaningful history event (most recent date wins) |
| `FILE_DATE` | History `Submitted`; else earliest history date; else early-stage `Current Status` date |
| `PERMIT_DATE` | `Permit Issued` (`Issued on MM/DD/YYYY`) or first history `Issued` |
| `FINAL_DATE` | Last final-like history event (`Permit Finaled`, `Permit Closed`, `CofO/CofC Issued`, `Completed`); else Final `Current Status` date |

Quirk: the date trailing `Current Status` (`… on MM/DD/YYYY`) is often one day after the matching history event. Existing `FINAL_DATE` values follow the history date, not the Current Status date.

## Field assessment

### STATUS_NORMALIZED — 123 missing, 57 incorrect (123 FILLED / 57 FIXED)

Before: Final 1,323 · Active 257 · In Review 171 · Inactive 128 · null 123.

Missing rows are exactly the `ladbs_no_history` set, filled from `Current Status`:

| Current Status | → STATUS_NORMALIZED | n |
| --- | --- | --- |
| Completed | Final | 52 |
| Application Submittal | In Review | 46 |
| Ready to Issue | In Review | 11 |
| Not Ready to Issue | In Review | 7 |
| Pending / Application Pending / other review | In Review | 7 |

Incorrect rows were driven by two patterns:

1. **STATUS_NORMALIZED ignored a final/expired Current Status** (e.g. 36 Active→Final where Current Status was already `Permit Finaled` / `CofO Issued` / `Permit Closed`).
2. **Stale Current Status vs newer history** (e.g. `PC Approved` display after `Application Withdrawn`; `Issued` display after `Permit Finaled`). Inference takes the more recent of Current Status vs the last *meaningful* history event, skipping clerical post-issuance rows like `Building Plans Picked Up` that would otherwise demote Issued/Finaled permits back to In Review.

FIXED transitions: Active→Final 36 · In Review→Active 10 · In Review→Final 7 · Active→Inactive 3 · Final→Active 1.

After repair: Final 1,417 · Active 229 · In Review 225 · Inactive 131 · null 0.

### FILE_DATE — mostly missing; fillable from history (1,327 FILLED / 0 FIXED)

- When present (601), `FILE_DATE` always matched the history `Submitted` date — no fixes needed.
- Of 1,401 missing values, 1,280 had history but no `Submitted` event (1,166 start at `Issued` — typical LADBS internet/express permits). Filled from the earliest history date as an application proxy.
- 1 additional missing row had a `Submitted` event and was filled from it.
- 46 `Application Submittal` no-history rows have no parseable status date (field ends with bare `on`) and remain empty along with other no-history rows whose only timestamp is a completion/ready date.

After repair: 74 still missing — all `ladbs_no_history` (`Completed` 52, `Ready to Issue` 11, `Not Ready to Issue` 7, `Pending` 4). Those status dates are not application dates, so they are not used as `FILE_DATE`.

Coverage after repair: Active 100% · Inactive 100% · Final 96.3% · In Review 90.2%.

### PERMIT_DATE — nearly complete for issued permits (10 FILLED / 0 FIXED)

Existing `PERMIT_DATE` matched `Permit Issued` / first `Issued` history event on all 1,698 comparable rows (0 mismatches).

Fills: 10 previously missing issuance dates on Active/Final/Inactive rows that had `Issued on …` in DATA.

After repair:

| Status | PERMIT_DATE present |
| --- | --- |
| Active | 229 / 229 (100%) |
| Final | 1,363 / 1,417 (96.2%) |
| Inactive | 116 / 131 (88.5%) |
| In Review | 0 / 225 (0%) |

The 54 Final rows still missing `PERMIT_DATE` are almost all `Completed` grading / demolition / sign rows with `Permit Issued == No` and empty history (never issued). The 15 Inactive gaps are withdrawn / never-issued applications.

### FINAL_DATE — incomplete on Final; rare spurious on others (122 FILLED / 6 FIXED)

Before repair, 28 Final rows lacked `FINAL_DATE` — mostly `Permit Closed` (history has the close date, but upstream only mapped `Permit Finaled`). After status fixes, additional newly-Final rows also needed fills. `Completed` no-history rows use the Current Status date.

FIXED (6): cleared spurious `FINAL_DATE` on rows whose effective status is not Final (including one Final→Active `CofO in Progress` case and Inactive revoked/expired rows that had retained an earlier final stamp).

After repair: Final 1,417 / 1,417 (100%) have `FINAL_DATE`; Active / In Review / Inactive have 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 123 | 57 | 123 → 0 |
| FILE_DATE | 1,327 | 0 | 1,401 → 74 |
| PERMIT_DATE | 10 | 0 | 304 → 294 |
| FINAL_DATE | 122 | 6 | 701 → 585 |

Remaining gaps are structural in DATA (no application date on Completed/ready no-history rows; no issuance on never-issued Completed/withdrawn rows), not repair bugs.

## Artifacts

- Script: `agent/scripts/data_repair_ca_los_angeles.py` (`data_repair` function)
- Report: `agent/reports/2026-07-24-los-angeles-data-repair.md`
