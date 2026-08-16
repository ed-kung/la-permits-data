# Allen (TX) data repair — STATUS_NORMALIZED and dates

**Summary:** Among TX sample jurisdictions ordered by name, Allen is the first without an existing repair script. Allen’s CivicPlus/EnerGov `DATA` payloads already align `FILE_DATE`/`PERMIT_DATE`/`FINAL_DATE` with `entity.ApplyDate`/`IssueDate`/`FinalDate` when present. The main defects are 17 unmapped `STATUS_NORMALIZED` values and 768 spurious `FINAL_DATE` values on non-Final rows (the agency stamps `FinalDate` even when the case is still issued, in review, or withdrawn). The repair fills those statuses, clears non-Final finals, and leaves true Final dates intact (960/960).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` (193,630 rows). Walking `(JURISDICTION, STATE)` in alphabetical order, existing TX scripts cover Abilene, Austin, Fort Worth, Houston, and San Antonio. **Allen** is the first gap → `agent/scripts/tx/data_repair_tx_allen.py`.

Sample size: **2,000** Allen records.

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Top-level keys |
| --- | ---: | --- |
| `entity_core` | 1,855 | contacts, details, entity, fees, processing_status |
| `entity_rich` | 144 | core + attachments, holds, more_info, reviews |
| `entity_minimal` | 1 | contacts, details, entity, processing_status (no fees) |

Repair logic uses `entity.CaseStatus`, `ApplyDate`, `IssueDate`, and `FinalDate` in all three variants.

## Field assessment (before repair)

### STATUS_NORMALIZED

Upstream mapping from `entity.CaseStatus` is mostly correct (`Completed`/`Certificate of Occupancy` → Final, `Permit Issued`/`Approved` → Active, review-like statuses → In Review, expired/withdrawn/void/revoked/denied → Inactive).

**Incorrectly missing (17):**

| CaseStatus | n | Expected |
| --- | ---: | --- |
| Requires Resubmittal | 9 | In Review |
| ROW Active Project | 8 | Active |

No incorrect non-null statuses found relative to `CaseStatus`.

### FILE_DATE

- Missing: **0 / 2,000**
- All values match `entity.ApplyDate` at calendar-day resolution
- No fill or fix needed

### PERMIT_DATE

- Present values: **1,809** — all match `entity.IssueDate`
- Missing: **191** (no `IssueDate` in DATA)
- Of Active/Final rows, only **3** lack `PERMIT_DATE` (and lack `IssueDate`): two `Completed`, one `Approved` — not fillable from DATA

Ideal coverage (Active + Final should have issuance): already ~99.8% where IssueDate exists.

### FINAL_DATE

- Present values match `entity.FinalDate` when both exist
- **All Final rows (960) already have FINAL_DATE**
- **Incorrect extras on non-Final rows:** Active 506, In Review 166, Inactive 79, plus the 17 null-status rows — agency `FinalDate` is often set on issued/in-review/withdrawn cases and is not a true completion/signoff for our schema
- Reason: upstream copied `FinalDate` indiscriminately; semantic rule is FINAL_DATE only for Final status

## Repair behavior

Canonical mappings:

- `CaseStatus` → `STATUS_NORMALIZED` (including the two previously unmapped values)
- `ApplyDate` → `FILE_DATE`
- `IssueDate` → `PERMIT_DATE` (whenever present)
- `FinalDate` → `FINAL_DATE` only when effective status is Final; otherwise clear

Flags: `FILLED` for former missings; `FIXED` for corrected or cleared values. `INFERRED_SCHEMA` set per row.

## Performance (after repair)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 17 | 0 | 17 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 191 → 191 |
| FINAL_DATE | 0 | 768 | 272 → 1,040 |

Status distribution after: Final 960, Active 579, Inactive 265, In Review 196 (no nulls).

Date coverage after repair:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 578 / 579 (99.8%) | 0 / 579 |
| Final | 958 / 960 (99.8%) | 960 / 960 (100%) |
| In Review | 70 / 196 (35.7%) | 0 / 196 |
| Inactive | 203 / 265 (76.6%) | 0 / 265 |

`FILE_DATE`: 2,000 / 2,000.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_allen.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_allen_repaired.parquet`
