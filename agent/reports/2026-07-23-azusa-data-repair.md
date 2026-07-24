# Azusa CA data repair

**Summary:** Azusa’s 2,000 sample records share one DATA schema (`system_status_data_details`) with dates under `Data Details` and lifecycle in `System Status`. The dominant error is `FINAL_DATE`: ~1,745 rows stored `Expire Date` (permit validity window) instead of `Final Date` (only 3 rows matched `Final Date`, all coincidentally equal to Expire). Status fixes: 9 Estimates mislabeled `Final` → `In Review`, 1 missing `B.L. HOLD` → `In Review`, and 14 rows where `STATUS_ORIGINAL` was stale vs `System Status`. `FILE_DATE` already matches `App. Date` for all rows. After repair: Active/Final `PERMIT_DATE` coverage is 100%/99.7%; Final `FINAL_DATE` coverage is 97.5% (33 Final/Completed rows lack `Final Date` in DATA). Script: `agent/scripts/data_repair_ca_azusa.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Azusa"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Azusa, CA (after Alhambra, Arcadia) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `system_status_data_details` | 2,000 |

All rows share the same top-level keys (`System Status`, `Data Details`, `Permit Type`, `Inspections`, etc.). Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `System Status` |
| `FILE_DATE` | `Data Details['App. Date']` |
| `PERMIT_DATE` | `Data Details['Issue Date']` |
| `FINAL_DATE` | `Data Details['Final Date']` |

`Data Details['Expire Date']` is a validity window (~6–12 months after issuance), not a finaling date. One Expire year of 2112 appears in the sample; the repair uses a 1980–2035 year gate for fill/fix sources and a separate ungated parse only to detect Expire-derived `FINAL_DATE` values.

## Field assessment

### STATUS_NORMALIZED — 24 incorrect / missing (1 FILLED / 23 FIXED)

Upstream mapping from `STATUS_ORIGINAL` (lowercased snapshot) was mostly right, but `System Status` in DATA is authoritative when they diverge (14 rows).

| System Status | Correct STATUS_NORMALIZED | n |
| --- | --- | --- |
| Final | Final | 1,297 |
| Completed | Final | 22 |
| Issued | Active | 332 |
| Open | In Review | 89 |
| Estimate | In Review | 9 |
| Hold / B.L. HOLD | In Review | 3 |
| Expired | Inactive | 211 |
| Void | Inactive | 34 |
| Canceled | Inactive | 3 |

Repairs:

| Before | After | Reason | n |
| --- | --- | --- | --- |
| Final | In Review | `Estimate` (no Issue/Final dates) | 9 |
| (missing) | In Review | `B.L. HOLD` | 1 |
| Active / In Review | Final | `System Status=Final`, stale ORIG | 8 |
| In Review | Active | `System Status=Issued`, stale ORIG | 4 |
| Active | Inactive | `System Status=Expired`, stale ORIG | 1 |
| Active | In Review | `System Status=Open`, stale ORIG | 1 |

After repair: Final 1,319, Active 332, Inactive 248, In Review 101 (0 missing).

### FILE_DATE — correct (0 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- All 2,000 rows populated; every value equals `Data Details['App. Date']`.
- Repair re-derives from `App. Date` for robustness but changes nothing on the sample.

### PERMIT_DATE — mostly correct; 5 FILLED (0 FIXED)

- Ideal: populated for Active and Final.
- When both present, `PERMIT_DATE` always matched `Issue Date` (1,882 / 1,882). 113 rows have both null.
- 5 `In Review`/`open` rows had `Issue Date` but null `PERMIT_DATE`; after status correction to Active (`System Status=Issued`), those 5 are FILLED.
- After repair: Active 332/332 (100%); Final 1,315/1,319 (99.7%). The 4 Final gaps have empty `Issue Date` in DATA (SF remodel, Electrical, Com alteration combo, PHOTOVOLTAIC SYSTEM).

### FINAL_DATE — systematically wrong (119 FILLED / 1,744 FIXED)

- Ideal: populated for Final records with the finaled / completion date.
- **Root cause:** upstream mapped `Expire Date` → `FINAL_DATE`. Among 1,747 non-null `FINAL_DATE` values, 1,745 equaled Expire and only 3 equaled Final Date (those 3 had Final == Expire).
- Repair: overwrite with `Final Date` when present; clear Expire-derived (or any) `FINAL_DATE` on non-Final rows; clear Expire-derived values on Final rows that lack `Final Date`.
- After repair: Final 1,286/1,319 (97.5%) have `FINAL_DATE`, all matching `Final Date`. Non-Final statuses have 0 `FINAL_DATE`.
- **Not repairable:** 33 Final/Completed rows (18 Final + 15 Completed, mostly legacy Building History / trades with `App. Date=5/4/1999`) have empty `Final Date`. Expire is not used as a proxy.

Missing `FINAL_DATE` rises from 253 → 714 because incorrect Expire values were cleared; that is expected.

## Repair function

`agent/scripts/data_repair_ca_azusa.py` → `data_repair(df)`

- Overwrites incorrect / missing fields from DATA
- Adds `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`} and `INFERRED_SCHEMA`
- Rejects implausible date years (1980–2035) before using them as fill/fix sources
- CLI preview on the LA sample:

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 1 | 23 | 1 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 5 | 0 | 118 → 113 |
| FINAL_DATE | 119 | 1,744 | 253 → 714 |

## Artifacts

- Repair script: `agent/scripts/data_repair_ca_azusa.py`
- Report: `agent/reports/2026-07-23-azusa-data-repair.md`
