# Claremont CA data repair

**Summary:** Claremont’s 2,000 sample records share one DATA schema (`system_status_data_details`) with dates under `Data Details` and lifecycle in compound `System Status` strings (e.g. `Final Final`, `Open Plan check`). The dominant error is `FINAL_DATE`: ~1,880 rows stored `Expire Date` (permit validity window) instead of `Final Date`. Status fixes: 24 Estimates mislabeled `Final` → `In Review`, 158 `Open Issued` mislabeled `In Review` → `Active`, 2 `Open Completed` → `Final`, and 1 stale `Final Final` labeled Active → Final. `FILE_DATE` already matches `App. Date` for all rows; `PERMIT_DATE` already matches `Issue Date` when both present. After repair: Active/Final `PERMIT_DATE` coverage is 94.4%/98.6%; Final `FINAL_DATE` coverage is 97.3% (28 Final rows lack `Final Date` in DATA). Script: `agent/scripts/data_repair_ca_claremont.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Claremont"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Claremont, CA (after Alhambra … Carson) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `system_status_data_details` | 2,000 |

All rows share the same top-level keys (`System Status`, `Data Details`, `Permit Type`, `Inspections`, etc.). Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `System Status` (full compound string) |
| `FILE_DATE` | `Data Details['App. Date']` |
| `PERMIT_DATE` | `Data Details['Issue Date']` |
| `FINAL_DATE` | `Data Details['Final Date']` |

`Data Details['Expire Date']` is a validity window (~6 months after issuance), not a finaling date. Same portal shape as Azusa; Claremont uses duplicated / compound status labels rather than single-token values.

## Field assessment

### STATUS_NORMALIZED — 185 incorrect (0 FILLED / 185 FIXED)

Upstream mapped from `STATUS_ORIGINAL` (first token of `System Status`, lowercased). That was mostly right, but several compound statuses and the Estimate mapping were wrong.

| System Status | Correct STATUS_NORMALIZED | n |
| --- | --- | --- |
| Final Final | Final | 1,022 |
| Open Completed | Final | 2 |
| Issued Issued | Active | 251 |
| Open Issued | Active | 158 |
| Open Plan check / Open Open / Open Copy | In Review | 164 |
| Estimate Estimate | In Review | 24 |
| Hold Hold | In Review | 57 |
| Expired Expired | Inactive | 294 |
| Void Void / Void Rescind | Inactive | 26 |
| Canceled Cancelled | Inactive | 2 |

Repairs:

| Before | After | Reason | n |
| --- | --- | --- | --- |
| Final | In Review | `Estimate Estimate` (pre-issuance; almost never has Issue/Final) | 24 |
| In Review | Active | `Open Issued` (all 158 have Issue Date / PERMIT_DATE) | 158 |
| In Review | Final | `Open Completed` | 2 |
| Active | Final | `Final Final` with stale `STATUS_ORIGINAL=issued` | 1 |

After repair: Final 1,024, Active 409, Inactive 322, In Review 245 (0 missing).

### FILE_DATE — correct (0 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- All 2,000 rows populated; every value equals `Data Details['App. Date']`.
- Repair re-derives from `App. Date` for robustness but changes nothing on the sample.

### PERMIT_DATE — correct where Issue Date exists (0 FILLED / 0 FIXED)

- Ideal: populated for Active and Final.
- When both present, `PERMIT_DATE` always matched `Issue Date` (1,713 / 1,713). 287 rows have both null.
- Remapping `Open Issued` → Active did not create new fills (those rows already had `PERMIT_DATE`).
- After repair: Active 386/409 (94.4%); Final 1,010/1,024 (98.6%).
- **Not repairable:** 23 `Issued Issued` and 14 `Final Final` rows have empty `Issue Date` in DATA. Approvals/Inspections carry counts only, no issuance dates. `FILE_DATE` is not used as a proxy.

### FINAL_DATE — systematically wrong (31 FILLED / 1,881 FIXED)

- Ideal: populated for Final records with the finaled / completion date.
- **Root cause:** upstream mapped `Expire Date` → `FINAL_DATE`. Among 1,881 non-null `FINAL_DATE` values, 1,880 equaled Expire; only 297 also equaled Final Date (those had Final == Expire). Zero Final-status rows matched `Final Date` before repair.
- Repair: overwrite with `Final Date` when present (965 FIXED + 31 FILLED on Final rows); clear Expire-derived (or any) `FINAL_DATE` on non-Final rows and on Final rows that lack `Final Date` (916 FIXED clears).
- After repair: Final 996/1,024 (97.3%) have `FINAL_DATE`, all matching `Final Date`. Non-Final statuses have 0 `FINAL_DATE`. Expire-only matches: 0.
- **Not repairable:** 28 Final rows (27 `Final Final` + 1 `Open Completed`) have empty `Final Date`. Expire is not used as a proxy.

Missing `FINAL_DATE` rises from 119 → 1,004 because incorrect Expire values were cleared; that is expected.

## Repair function

`agent/scripts/data_repair_ca_claremont.py` → `data_repair(df)`

- Overwrites incorrect / missing fields from DATA
- Adds `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`} and `INFERRED_SCHEMA`
- Rejects implausible date years (1980–2035) before using them as fill/fix sources
- CLI preview on the LA sample:

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 185 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 287 → 287 |
| FINAL_DATE | 31 | 1,881 | 119 → 1,004 |

## Artifacts

- Repair script: `agent/scripts/data_repair_ca_claremont.py`
- Report: `agent/reports/2026-07-24-claremont-data-repair.md`
