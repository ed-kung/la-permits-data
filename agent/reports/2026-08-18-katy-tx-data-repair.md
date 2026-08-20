# Katy (TX) data repair

**Summary:** Katy was the first TX sample jurisdiction lacking a repair script. Its CivicPlus/EnerGov `DATA` JSON uses a single `entity_rich` key set. Repairing from `PermitStatus`/`CaseStatus`, `ApplyDate`, `IssueDate`, and `FinalDate`/`FinalizeDate` filled all 22 missing statuses, fixed 8 stale Active→Final rows (PermitStatus already Complete), filled 8 missing final dates on those rows, and cleared 39 spurious `FINAL_DATE` values on non-Final rows. `FILE_DATE` was already complete and correct; `PERMIT_DATE` needed no changes. Remaining gaps are structural: 4 Complete rows with no `IssueDate`, and 4 Complete rows with no final timestamp.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover Austin through Lewisville; **Katy** is the first without a script (2,000 sample rows).

## DATA schema

| INFERRED_SCHEMA | n |
| --- | ---: |
| `entity_rich` (attachments, contacts, details, entity, fees, holds, more_info, processing_status, reviews) | 2,000 |

`attachments`, `contacts`, `holds`, `more_info`, `processing_status`, and `reviews` are present as keys but null/empty on every sample row. Status and date repair uses only `entity` / `details`.

Canonical sources:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `details.PermitStatus` when Complete, else `entity.CaseStatus` |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate`, else `details.IssueDate` |
| `FINAL_DATE` (Final only) | `entity.FinalDate`, else `details.FinalizeDate` |

Preferring Complete on either portal status field matters: on 8 rows `PermitStatus=Complete` while `CaseStatus` / `STATUS_ORIGINAL` still say Issued.

## Findings by field

### STATUS_NORMALIZED

Before repair: Final 1,624 / Inactive 227 / Active 115 / In Review 12 / **missing 22**.

Missing statuses were unmapped `STATUS_ORIGINAL` values that appear cleanly in `CaseStatus` / `PermitStatus`:

| STATUS_ORIGINAL | Expected | n |
| --- | --- | ---: |
| requires resubmittal | In Review | 14 |
| review approved | In Review | 8 |

Additionally, 8 rows had `PermitStatus=Complete` (with `FinalizeDate` present) while `CaseStatus` / `STATUS_ORIGINAL` remained `Issued` and `STATUS_NORMALIZED` remained Active → FIXED to Final.

**After repair:** Final 1,632 / Inactive 227 / Active 107 / In Review 34 / missing 0. Flags: **22 FILLED**, **8 FIXED**.

### FILE_DATE

All 2,000 rows already had `FILE_DATE`, and every value matched `entity.ApplyDate` at calendar-day resolution. (`details.ApplyDate` can differ by one calendar day on a handful of UTC-boundary rows; the existing field tracks entity local time.) **0 FILLED / 0 FIXED.**

### PERMIT_DATE

Ideal: populated for Active and Final.

- When `IssueDate` is present, existing `PERMIT_DATE` already matches at calendar-day resolution (0 mismatches) → **0 FILLED / 0 FIXED**.
- **4 Final** rows remain without `PERMIT_DATE`: Complete Private Water Well Sample / Fire Sprinkler / Residential Sewer Tap cases with `Issued=False` and null `IssueDate` (no issuance timestamp in DATA). All four do have a final timestamp.
- Active coverage after repair: **107/107 (100%)**. Final: **1,628/1,632 (99.8%)**.

The other 108 missing `PERMIT_DATE` values are on In Review / Inactive rows where issuance never occurred (Void, Denied, Submitted, etc.) — expected.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- **8 FILLED** on the Active→Final remaps, from `details.FinalizeDate` (entity `FinalDate` still null on those rows).
- **39 FIXED** clears of spurious `FINAL_DATE` on non-Final rows (Void 27, Expired 7, Issued 2, Review Approved 2, Denied 1).
- **4 Final** rows still lack a final timestamp (New Single Family, commercial build-out, Certificate of Occupancy, commercial electrical) — both `FinalDate` and `FinalizeDate` null.

After repair: Final **1,628/1,632 (99.8%)**; Active / In Review / Inactive all 0%. Date-order violations (FILE>PERMIT, PERMIT>FINAL, FILE>FINAL): **0**.

## Repair script

- Script: `agent/scripts/tx/data_repair_tx_katy.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_katy_repaired.parquet`

### Performance (sample n=2,000)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 22 | 8 | 22 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 112 → 112 |
| `FINAL_DATE` | 8 | 39 | 341 → 372 |

(`FINAL_DATE` missing count rises because 39 non-Final clears outweigh the 8 fills — desired under the Final-only rule.)
