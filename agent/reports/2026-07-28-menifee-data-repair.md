# Menifee (CA) data repair

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for the first jurisdiction in `permits_ca_sample.parquet` lacking a repair script (Menifee, CA; n=2,000). DATA is an Accela Citizen Access scrape. FILE_DATE was already correct for all rows. Status and FINAL_DATE had the most recoverable errors; PERMIT_DATE was largely correct when present, with a small set of spurious In Review dates cleared and a few Certificate Issuance fills.

## Jurisdiction selection

Went down (JURISDICTION, STATE) pairs in sample order. First missing script under `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Menifee, CA** → `agent/scripts/ca/data_repair_ca_menifee.py`.

## DATA shape / INFERRED_SCHEMA

Top-level keys are nearly uniform (`status`, `date`, `tasks`, `inspections`, `search_data`, `more_details`, …). Content variants:

| Schema | Count | Notes |
| --- | ---: | --- |
| `accela_tasks` | 1,562 | Dated workflow events under `tasks` |
| `accela_shell` | 390 | Task shells, no dated events (often TBD-only) |
| `accela_historical` | 48 | Single `Historical` task; dates often only on inspections |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,033 / Active 579 / In Review 340 / Inactive 23 / null 25.
- Upstream mapper missed `Mylars in Review` and `Awaiting Mylar Submittal` (null).
- Stale vs `DATA.status`: 4 `Finaled` still Active; several issued-phase statuses still In Review; 34 planning `Approved` (no issuance) coded Active.
- Repair maps Accela status → Active / Final / In Review / Inactive, and promotes In Review → Active when a Permit/Certificate Issuance `Issued` event exists.
- **FILLED 15, FIXED 44**; nulls fall from 25 → 10 (blank status only).

### FILE_DATE

- Canonical source: `DATA.date` (else `search_data.Date`).
- All 2,000 rows already match → **no FILE_DATE changes** (100% coverage).

### PERMIT_DATE

- Canonical source: earliest `Permit Issuance` or `Certificate Issuance` marked `Issued` (not Ready to Issue / Conditions of Approval).
- When extractable, existing PERMIT_DATE matched in essentially all cases (0 day mismatches).
- Spurious PERMIT_DATE on In Review / mylar rows often came from `Conditions of Approval/Complete` → cleared.
- Active/Final shells without an Issued event (Historical / TBD-only) remain missing (~14% Active, ~9% Final after repair).
- **FILLED 3, FIXED 14** (mostly clears). Missing count 570 → 581 because clears outweigh fills.

### FINAL_DATE

- Canonical source: earliest `Inspection` marked `Final Inspection Complete` (matches upstream Menifee coding), else `Closed`/`Close`, else `Certificate of Occupancy`/`Final CO Issued`, else earliest final-titled passed/complete inspection.
- Final missing FINAL_DATE often recoverable from inspections on historical/shell rows.
- 3 non-Final rows had spurious FINAL_DATE → cleared.
- **FILLED 160, FIXED 3**. Final FINAL_DATE coverage after repair: **1,002 / 1,037 (96.6%)**. Missing before 1,155 → after 998.

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 15 | 44 | 25 → 10 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 3 | 14 | 570 → 581 |
| FINAL_DATE | 160 | 3 | 1,155 → 998 |

After repair, PERMIT_DATE coverage: Active 86.3%, Final 91.2%, In Review 0%. FINAL_DATE: Final 96.6%, other statuses 0%. Chronology: 7 pre-existing FILE > PERMIT inversions unchanged; 0 PERMIT > FINAL.

## Not repairable from DATA

- 10 blank-status shells → STATUS stays null.
- Active/Final without Issued task events → PERMIT_DATE stays missing.
- ~35 Final rows with no Final Inspection Complete / Closed / CofO / usable final inspection → FINAL_DATE stays missing.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_menifee.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/menifee_repaired_sample.parquet`
