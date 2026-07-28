# Davis (CA) data repair — 2026-07-28

Davis was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. The city uses the same permit-portal scrape family as Bakersfield (`detail` + optional `permit_status_detail` / `insp_status_detail`). `STATUS_NORMALIZED` was missing on 99.5% of rows and is now fully populated from `Application Status`; `FILE_DATE` was already correct; issuance and final dates are almost never present in `DATA`, so `PERMIT_DATE` / `FINAL_DATE` remain largely missing after a handful of fixes on the 10 rows with permit-detail blocks.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Davis, CA** → `agent/scripts/ca/data_repair_ca_davis.py` (n=1,999).

## DATA schema

Top-level keys are stable (`detail`, `fees`, `fees_total`, and usually `insp_status` / `permit_status` / `*_detail`). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_status` | 1,985 | Status headers present; `permit_status_detail` null or `{}` |
| `portal_detail` | 10 | Nonempty `permit_status_detail` (Issue / Permit / Expiration dates) |
| `detail_only` | 4 | `detail` (+ fees) only |

`detail.Application Status` is present on every row. Date-bearing fields beyond `Application Date` appear almost exclusively inside the 10 `portal_detail` rows.

## Field assessment

### STATUS_NORMALIZED

- Missing on 1,989 / 1,999 before repair. `STATUS_ORIGINAL` is null or `{}` on those rows; only 10 recent scrapes carried a usable original status.
- Mapping from `Status for Permit Number` (when present) else `Application Status`:
  - Final: `PERMIT COMPLETED`, `CERTIFICATE ISSUED`, `CLOSED` (permit: `CLOSED`)
  - Active: `PERMIT HAS BEEN ISSUED` (permit: `PERMIT PRINTED`)
  - In Review: `IN PLAN CHECK`, `APPROVED` (permit: `TO BE ISSUED`)
  - Inactive: withdrawn / expired* / rescinded / rejected
- The 10 pre-labeled rows already matched this mapping (no FIXED).
- **Repair:** **1,989 FILLED**. Missing after: 0.

### FILE_DATE

- Populated for 100% of rows; equals `detail.Application Date` on every sample row.
- **Repair:** no changes (0 FILLED / 0 FIXED).

### PERMIT_DATE

- Missing on 1,989 / 1,999 before repair. Only the 10 `portal_detail` rows have Issue/Permit dates in `DATA`.
- On Active (`PERMIT PRINTED`) rows, `Issue Date == Permit Date` and matched the existing `PERMIT_DATE`.
- On Final (`CLOSED`) rows, `Permit Date` had been overwritten to the finalization date and was incorrectly stored as `PERMIT_DATE`; true issuance is `Issue Date` → **2 FIXED**.
- On In Review (`TO BE ISSUED`) rows, `Issue Date` is empty and `Permit Date` is not an issuance → clear spurious `PERMIT_DATE` → **3 FIXED**.
- Remaining Active/Final rows have no issue date in `DATA` → stay missing.
- **Repair:** **0 FILLED**, **5 FIXED**. Missing after: 1,992.

### FINAL_DATE

- Missing on 1,997 / 1,999 before repair. The only two populated values are the `CLOSED` `portal_detail` rows; both already equal the latest `APPROVED` inspection completion date (and the closed `Permit Date`).
- Recoverable sources: (1) latest `APPROVED` inspection result date on/after `FILE_DATE`; (2) `Permit Date` when `Status for Permit Number == CLOSED`.
- Nearly all Final rows (`PERMIT COMPLETED` / `CERTIFICATE ISSUED`) lack dated inspections and closed permit detail → cannot fill from `DATA`.
- **Repair:** **0 FILLED / 0 FIXED**. Missing after: 1,997 (both existing Final dates retained).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1,989 | 0 | 1,989 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 5 | 1,989 | 1,992 |
| FINAL_DATE | 0 | 0 | 1,997 | 1,997 |

Status distribution after repair: Final 1,789 · Active 117 · Inactive 54 · In Review 39.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 4.3% | 0% |
| Final | 100% | 0.1% | 0.1% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 0% | 0% |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_davis.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/davis_repaired_sample.parquet`
