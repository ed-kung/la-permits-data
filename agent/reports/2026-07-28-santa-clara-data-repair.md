# Santa Clara (CA) data repair — 2026-07-28

Santa Clara was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` already has correct `FILE_DATE` for all 2,001 rows; `STATUS_NORMALIZED` needed 14 stale-status fixes; `FINAL_DATE` was entirely missing and is now filled for 98.6% of Final records; `PERMIT_DATE` remains largely missing on older shell records that lack Ready-to-Issue workflow events.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Santa Clara, CA** → `agent/scripts/ca/data_repair_ca_santa_clara.py` (n=2,001).

## DATA schema

All rows share the same Accela top-level keys (`status`, `date`, `tasks`, `inspections`, `search_data`, `more_details`, …). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_shell` | 1,507 | Task list present, no dated events (mostly pre-~2021) |
| `accela_tasks` | 493 | Dated workflow events under `tasks` |
| `accela_search_only` | 1 | No tasks |

## Field assessment

### STATUS_NORMALIZED

- No missing values before repair.
- Mapping from `DATA.status` / `search_data.Status` is clean (`Finaled`/`Closed`/`TCO Issued` → Final; `Issued`/`Active` → Active; review statuses → In Review; cancelled/expired → Inactive).
- **Issue:** `STATUS_NORMALIZED` was derived from `STATUS_ORIGINAL`, which lags `DATA.status` on 14 rows (e.g. `Finaled` still labeled Active; `Issued` labeled In Review; `Cancelled`/`Permit Expired` still Active).
- **Repair:** overwrite from `DATA.status` → **14 FIXED**.

### FILE_DATE

- Already populated for 100% of rows; equals top-level `DATA.date` (and `search_data.Date`) on every sample row.
- **Repair:** no changes (0 FILLED / 0 FIXED).

### PERMIT_DATE

- Missing on 1,702 / 2,001 (85%). Among Active/Final before repair: Active 85% present, Final only 12% present.
- When present, dates match `Ready to Issue` → `Issued` workflow marks exactly (298/299); the one mismatch was a Reviews Complete (In Review) row whose date was a planning-approval stamp while Ready to Issue was still `TBD`.
- Older Accela shells almost never retain dated Ready-to-Issue events, so issuance cannot be recovered from `DATA` for ~1.3k Active/Final rows. Earliest inspection dates correlate with issuance but are not used (post-issuance proxy only).
- **Repair:** **3 FILLED** (Issued rows previously mislabeled In Review), **1 FIXED** (cleared spurious In Review permit date). Missing after: 1,700.

### FINAL_DATE

- Missing on 100% of rows before repair, including all Final records.
- Recoverable from (1) `Active Permit` marked `Finaled` / `Final` / `Closed`, else (2) latest inspection titled `*FINAL*` with status Pass / Done / Approved. Floor on `PERMIT_DATE` only when known — converted historical shells keep mid-century inspection finals even when `FILE_DATE` is a later Accela load date.
- **Repair:** **1,532 FILLED** (98.6% of 1,553 Final after status fix). Remaining ~21 Final/Closed/TCO child records have neither workflow final marks nor a usable final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 14 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 3 | 1 | 1,702 | 1,700 |
| FINAL_DATE | 1,532 | 0 | 2,001 | 469 |

Status distribution after repair: Final 1,553 · Inactive 182 · In Review 154 · Active 112.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 84.8% | 0% |
| Final | 100% | 12.7% | 98.6% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 4.4% | 0% |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_santa_clara.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/santa_clara_repaired_sample.parquet`
