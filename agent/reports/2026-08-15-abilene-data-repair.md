# Abilene (TX) data repair

**Summary:** First TX sample jurisdiction without an existing repair script (sorted by STATE, JURISDICTION) was **Abilene**. DATA is a flat city permit-list scrape (`Completed`, `Date issued`, `Inspection` list). Upstream `STATUS_NORMALIZED` was null for all 2,000 rows because `STATUS_ORIGINAL` was just `Completed` lowercased (`yes`/`no`), not a real status. After repair: status fully populated (Final 1,909 / Inactive 72 / Active 19); PERMIT_DATE remains 100% and matches `Date issued`; Final FINAL_DATE is **100%**; spurious FINAL_DATE on 3 Active rows cleared. FILE_DATE cannot be recovered (no application date in DATA).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs sorted by state then jurisdiction. Existing TX scripts covered Austin, Fort Worth, and Houston; **Abilene** was the first missing (`agent/scripts/tx/data_repair_tx_abilene.py`).

## DATA shape

2,000 rows. Single key-set variant:

| INFERRED_SCHEMA | n |
| --- | ---: |
| `permit_list` | 2,000 |

Top-level keys (all rows): `Owner`, `Address`, `Comment`, `Permit #`, `Completed`, `Contractor`, `Inspection`, `Date issued`, `Description`, `Permit type`.

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Completed` + whether any `Inspection[*].Passed == Yes` |
| FILE_DATE | *(none — not recoverable)* |
| PERMIT_DATE | `Date issued` |
| FINAL_DATE | max `Inspection date` among Passed=Yes (Final only) |

## Field assessments

### STATUS_NORMALIZED

Before: **null 2,000**. `STATUS_ORIGINAL` is `yes` (1,981) / `no` (19), a 1:1 copy of `DATA.Completed`, not a permit lifecycle status — so nothing was ever mapped into `STATUS_NORMALIZED`.

Repair mapping:

| Signal | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| `Completed=Yes` and ≥1 Passed inspection | Final | 1,909 |
| `Completed=Yes` and no Passed inspection | Inactive | 72 |
| `Completed=No` | Active | 19 |

Inactive rows are closed/expired without a successful final (inspection notes such as “PERMIT EXPIRED”, “NO FINAL INSPECTION”, “NEVER BUILT”), consult-only failed inspections, or empty inspection lists — not true finals despite `Completed=Yes`.

After: Final 1,909 / Inactive 72 / Active 19 / **null 0**. FILLED 2,000, FIXED 0. No `In Review` signal exists in DATA.

### FILE_DATE

Before/after: **0/2,000** present. DATA has only `Date issued` (issuance). Treating issuance as an application/submittal date would be incorrect, so FILE_DATE is left missing. Not repairable from this payload.

### PERMIT_DATE

Before: **0 missing**. Every row already equals `Date issued` at day resolution. After repair: still 100% for Active, Final, and Inactive. FILLED 0, FIXED 0. Script still overwrites mismatches if they appear later.

### FINAL_DATE

Before: 88 missing (4.4%). Among rows that later become Final, all 1,909 already had FINAL_DATE equal to the latest Passed inspection date (0 mismatches).

Issues repaired:
- **3 FIXED**: `Completed=No` (Active) rows had FINAL_DATE set from an intermediate Passed inspection (rough-in / duct / etc.) despite not being completed → cleared.

After: Final FINAL_DATE **1,909/1,909 (100%)**; Active/Inactive **0**. The 72 Inactive rows correctly remain without FINAL_DATE (no Passed inspection to use as a completion stamp). Missing count rises 88 → 91 solely from clearing the three Active spurious dates.

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_abilene.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2,000 | 0 | 2,000 → 0 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 0 | 0 | 0 → 0 |
| FINAL_DATE | 0 | 3 | 88 → 91 |

Coverage after repair (by repaired status):

| Status | n | PERMIT_DATE | FINAL_DATE | FILE_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 19 | 100% | 0% | 0% |
| Final | 1,909 | 100% | 100% | 0% |
| Inactive | 72 | 100% | 0% | 0% |

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_abilene.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_abilene_repaired.parquet`
