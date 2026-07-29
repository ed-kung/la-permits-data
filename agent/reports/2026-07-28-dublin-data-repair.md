# Dublin (CA) data repair — 2026-07-28

Dublin was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela-style JSON under `DATA` (all 2,000 rows) already has correct `STATUS_NORMALIZED` and `FILE_DATE`. The repair fills 29 missing `PERMIT_DATE` values on Active/Final rows from `main.Approved` when `Issued` is blank, and clears 34 spurious `FINAL_DATE` values on canceled Inactive rows.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Dublin, CA** → `agent/scripts/ca/data_repair_ca_dublin.py` (n=2,000).

## DATA schema

Every sample row shares the same Accela-style top-level keys (`main`, `details`, `fees`, `address`, `parcel`, `actions`, `routing`, `valuation`, `conditions`, `contractors`, `description`, `permit_number`). Canonical dates/status live under `main` (`Status`, `Applied`, `Issued` / `Approved`, `Final`). `Expires` is a validity window, not a completion date. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `main_issued_finaled` | 1,756 | Issued + Final present |
| `main_issued` | 152 | Issued present, Final blank |
| `main_applied_only` | 37 | only Applied populated |
| `main_finaled_only` | 33 | Final present, Issued blank |
| `main_approved_only` | 22 | Approved present, Issued/Final blank |

## Field assessment

### STATUS_NORMALIZED

- No missing values (0 / 2,000). `STATUS_ORIGINAL` equals `main.Status` on every row.
- Upstream mapping is already correct: `final`→Final (1,773), `issued`→Active (111), `approved`→Active (11), `pending`→In Review (27), `expired`→Inactive (42), `canceled`→Inactive (36).
- 34 canceled rows carry `main.Final` (close/void stamp). Status correctly stays Inactive; do not promote to Final.
- **Repair:** 0 FILLED, 0 FIXED.

### FILE_DATE

- Present on all 2,000 rows; every value matches `main.Applied` at day resolution.
- **Repair:** 0 FILLED, 0 FIXED. Coverage 2,000 / 2,000 (100%).

### PERMIT_DATE

- Missing on 92 / 2,000. When present, every value matches `main.Issued` (0 incorrect).
- Fillable gaps (Issued blank, Approved present):
  - 11 Active `approved` rows → FILLED from Approved
  - 18 Final rows (mostly planning/zoning/addressing shells) → FILLED from Approved
- Unfillable by design: 27 In Review (`pending`), plus Inactive rows without Issued (already outside the Active/Final contract).
- **Repair:** 29 FILLED, 0 FIXED. Missing after: 63.
- Post-repair Active PERMIT coverage: 122/122 (100%); Final: 1,773/1,773 (100%).

### FINAL_DATE

- Missing on 211 / 2,000. When present, every value matches `main.Final` (0 incorrect).
- Among Final: 18 still missing FINAL — planning / zoning / COVID temp-use / addressing shells with blank `main.Final` and empty `actions`. No reliable fill source (action-level `* FINAL *` dates often disagree with `main.Final` elsewhere, so they are not used as overrides).
- **Spurious FINAL_DATE:** 34 Inactive `canceled` rows carried `main.Final` as a close stamp → cleared (FIXED).
- **Repair:** 0 FILLED, 34 FIXED (clear). Missing after: 245.
- Post-repair Final FINAL coverage: 1,755/1,773 (99.0%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 29 | 0 | 92 | 63 |
| FINAL_DATE | 0 | 34 | 211 | 245 |

Status distribution unchanged (Final 1,773 / Active 122 / Inactive 78 / In Review 27).

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 122 | 100% | 100% | 0% |
| Final | 1,773 | 100% | 100% | 99.0% |
| In Review | 27 | 100% | 0% | 0% |
| Inactive | 78 | 100% | 53.8% | 0% |

Chronology after repair: 0 `PERMIT < FILE`, 0 `FINAL < PERMIT`.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_dublin.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_dublin_repaired.parquet`
