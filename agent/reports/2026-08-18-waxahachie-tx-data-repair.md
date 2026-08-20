# Waxahachie (TX) data repair

**Summary:** Waxahachie was the first TX sample jurisdiction lacking a repair script. Its CivicPlus/EnerGov `DATA` JSON uses `entity_core` (1,962) and `entity_rich` (38) key sets. `STATUS_NORMALIZED`, `FILE_DATE`, and `PERMIT_DATE` already matched portal fields. The main defects were 140 spurious `FINAL_DATE` values on non-Final rows (cleared) and 542 Final rows missing a final timestamp despite null `FinalDate`/`FinalizeDate`. Filling from Passed Final* `processing_status` inspections (guarded to be on/after `IssueDate`) recovered 489 of those. Remaining gaps: 15 Active/Final rows with no `IssueDate`, 53 Final rows with no usable final timestamp, and one portal `FinalDate` that precedes `IssueDate`.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover Austin through Leander; **Waxahachie** is the first without a script (2,000 sample rows).

## DATA schema

| INFERRED_SCHEMA | n |
| --- | ---: |
| `entity_core` (contacts, details, entity, fees, processing_status) | 1,962 |
| `entity_rich` (entity_core + attachments, holds, more_info, reviews) | 38 |

Both schemas share the same `entity` / `details` date and status fields. `CaseStatus` equals `PermitStatus` on every sample row. `processing_status` is a non-empty inspection list on 1,489 rows (null on 511) and is used only as a `FINAL_DATE` fallback.

Canonical sources:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (equiv. `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate`, else `details.IssueDate` |
| `FINAL_DATE` (Final only) | `entity.FinalDate`, else `details.FinalizeDate`, else latest Passed `processing_status` row whose description contains `Final` (and whose date is on/after `IssueDate`) |

Status map (portal → normalized): Finaled / Complete → Final; Active / Issued / Inspection Pending → Active; Applied for / Submitted / Submitted - Online / In Review / On Hold / Fees Due → In Review; Void / Expired / Plan Approval Expired / Denied → Inactive.

## Findings by field

### STATUS_NORMALIZED

Before repair: Final 1,341 / Active 428 / Inactive 175 / In Review 56 / missing 0.

Portal `CaseStatus` inventory: Finaled 849, Complete 492, Active 342, Expired 119, Issued 84, Void 38, In Review 19, Applied for 18, Denied 16, On Hold 12, Fees Due 4, Plan Approval Expired 2, Submitted 2, Inspection Pending 2, Submitted - Online 1.

Every row’s `STATUS_NORMALIZED` already matched the map above (cross-tab with `CaseStatus` is diagonal). **0 FILLED / 0 FIXED.**

### FILE_DATE

All 2,000 rows already had `FILE_DATE`, and every value matched `entity.ApplyDate` at calendar-day resolution. **0 FILLED / 0 FIXED.**

Three rows have `ApplyDate` one calendar day after `IssueDate` (UTC-boundary / backdated IssueDate artifacts). Those FILE>PERMIT quirks are left as-is because both timestamps match DATA.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When `IssueDate` is present (1,870 rows), existing `PERMIT_DATE` already matches at calendar-day resolution → **0 FILLED / 0 FIXED**.
- **1 Active** row and **14 Final** rows (7 Finaled + 7 Complete) have `Issued=False` and null `IssueDate` → `PERMIT_DATE` stays missing (no issuance timestamp in DATA).
- Remaining missing `PERMIT_DATE` values are on In Review / Inactive rows where issuance never occurred (expected).

After repair coverage: Active **427/428 (99.8%)**, Final **1,327/1,341 (99.0%)**. In Review 5.4%; Inactive 64.6% (Expired/Void/Denied rows that were previously issued — expected).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Among Final rows, 799 already had `FINAL_DATE` matching `entity.FinalDate` / `details.FinalizeDate` (939 FinalDate-present rows include non-Final statuses that also carry a FinalDate stamp in DATA).
- **542 Final** rows had null `FinalDate` and null `FINAL_DATE` (474 Complete + 68 Finaled). Of these, 523 had a Passed Final* inspection (`Final`, `Final Building`, or `Final Electrical`); after requiring the inspection date ≥ `IssueDate`, **489 FILLED**.
- **140 FIXED** clears of spurious `FINAL_DATE` on non-Final rows (Active 47, Issued 46, Void 30, Denied 10, Expired 5, Plan Approval Expired 1, Inspection Pending 1). Those rows still have `FinalDate` in DATA (often equal to Apply/Issue day on legacy Active garage permits, or a close/deny stamp on Void/Denied) but should not carry a normalized finaled date.
- **53 Final** rows still lack a final timestamp: 19 with no Final* Passed inspection, plus 34 whose only Final* `scheduled_date` predates `IssueDate` (rejected by the order guard).
- **193** of the 489 fills land on calendar day `2021-05-27`, consistent with a portal migration backfill on older Complete cases; retained as the only Final* signal available.
- One pre-existing Final row keeps `FinalDate` before `IssueDate` (portal artifact; PERMIT>FINAL=1 after repair).

After repair: Final **1,288/1,341 (96.0%)**; Active / In Review / Inactive all 0%. Date-order violations: FILE>PERMIT=3, PERMIT>FINAL=1, FILE>FINAL=0.

## Repair script

- Script: `agent/scripts/tx/data_repair_tx_waxahachie.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_waxahachie_repaired.parquet`

### Performance (sample n=2,000)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 0 | 0 | 0 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 130 → 130 |
| `FINAL_DATE` | 489 | 140 | 1,061 → 712 |
