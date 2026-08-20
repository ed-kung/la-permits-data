# Kyle (TX) data repair

**Summary:** Kyle was the first TX sample jurisdiction lacking a repair script. Its CivicPlus/EnerGov `DATA` JSON uses `entity_core` (1,893) and `entity_rich` (107) key sets. Repairing from `PermitStatus`/`CaseStatus`, `ApplyDate`, `IssueDate`, and `FinalDate`/`FinalizeDate` fixed 32 stale statuses (18 Active→Final, 7 In Review→Active, 5 Active→Inactive, 2 Inactive→Final), filled 7 missing permit dates and 20 missing final dates on remapped Final rows, and cleared 14 spurious `FINAL_DATE` values on non-Final rows. `FILE_DATE` was already complete and correct. Remaining gaps are structural: 35 Active / 4 Final rows with no `IssueDate`, and 1 Complete row with no final timestamp.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover Austin through Katy; **Kyle** is the first without a script (2,000 sample rows).

## DATA schema

| INFERRED_SCHEMA | n |
| --- | ---: |
| `entity_core` (contacts, details, entity, fees, processing_status) | 1,893 |
| `entity_rich` (entity_core + attachments, holds, more_info, reviews) | 107 |

Both schemas share the same `entity` / `details` date and status fields. `processing_status` holds inspection history on 1,209 rows (null on 791) but is not needed for status/date repair.

Canonical sources:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | Prefer Complete / Issued on either `details.PermitStatus` or `entity.CaseStatus`; else map `CaseStatus`, falling back to `PermitStatus` |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate`, else `details.IssueDate` |
| `FINAL_DATE` (Final only) | `entity.FinalDate`, else `details.FinalizeDate` |

Preferring Complete / Issued on either portal status field matters: `PermitStatus` can advance ahead of `CaseStatus` / `STATUS_ORIGINAL`.

## Findings by field

### STATUS_NORMALIZED

Before repair: Inactive 718 / Final 596 / Active 536 / In Review 150 / missing 0. No unmapped statuses — every `STATUS_ORIGINAL` already mapped to a normalized value — but 32 rows lagged the current portal status:

| STATUS_ORIGINAL | Before | After | n | Cause |
| --- | --- | --- | ---: | --- |
| issued | Active | Final | 18 | CaseStatus and/or PermitStatus already Complete |
| in review | In Review | Active | 7 | CaseStatus and/or PermitStatus already Issued |
| issued | Active | Inactive | 5 | CaseStatus/PermitStatus already Expired |
| expired | Inactive | Final | 2 | CaseStatus/PermitStatus already Complete |

Portal status inventory (CaseStatus): Expired 617, Complete 613, Issued 521, In Review 134, Void 83, Plan Approval Expired 14, Denied 7, Submitted-Online 5, Plan Approved 2, Submitted 2, Closed 1, On Hold 1.

**After repair:** Inactive 721 / Final 616 / Active 520 / In Review 143 / missing 0. Flags: **0 FILLED**, **32 FIXED**.

### FILE_DATE

All 2,000 rows already had `FILE_DATE`, and every value matched `entity.ApplyDate` at calendar-day resolution. **0 FILLED / 0 FIXED.**

Five rows have ApplyDate one calendar day after IssueDate (UTC-boundary / backdated IssueDate artifacts in the portal). Those FILE>PERMIT order quirks are left as-is because both timestamps match DATA.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When `IssueDate` is present, existing `PERMIT_DATE` already matches at calendar-day resolution → **7 FILLED** (all on In Review→Active remaps that had IssueDate in DATA but null PERMIT_DATE) / **0 FIXED**.
- **35 Active** rows remain without `PERMIT_DATE`: portal status Issued with `Issued=False` and null IssueDate (legacy numeric permit numbers; no issuance timestamp in DATA).
- **4 Final** rows remain without `PERMIT_DATE`: Complete cases with `Issued=False` and null IssueDate (three still have FinalDate; one has neither IssueDate nor FinalDate).

After repair coverage: Active **485/520 (93.3%)**, Final **612/616 (99.4%)**. In Review 0%; Inactive 85.9% (Expired/Void rows that were previously issued — expected).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- **20 FILLED** on Active/Inactive→Final remaps, from `entity.FinalDate` / `details.FinalizeDate`.
- **14 FIXED** clears of spurious `FINAL_DATE` on non-Final rows (13 Issued still Active; 1 Plan Approval Expired).
- **1 Final** row still lacks a final timestamp (BL1501076): both `FinalDate` and `FinalizeDate` null.

After repair: Final **615/616 (99.8%)**; Active / In Review / Inactive all 0%. Date-order violations: FILE>PERMIT=5 (portal artifacts above), PERMIT>FINAL=0, FILE>FINAL=0.

## Repair script

- Script: `agent/scripts/tx/data_repair_tx_kyle.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_kyle_repaired.parquet`

### Performance (sample n=2,000)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 0 | 32 | 0 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 7 | 0 | 291 → 284 |
| `FINAL_DATE` | 20 | 14 | 1,391 → 1,385 |
