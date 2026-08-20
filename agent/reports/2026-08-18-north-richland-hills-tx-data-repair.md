# North Richland Hills (TX) data repair

**Summary:** North Richland Hills was the first TX sample jurisdiction lacking a repair script. Its CivicPlus/EnerGov `DATA` JSON uses `entity_core` (1,737) and `entity_rich` (263) key sets. `FILE_DATE` and `PERMIT_DATE` already matched portal fields. Repairs filled 23 missing `STATUS_NORMALIZED` values (hold / incomplete-submittal statuses → In Review), fixed 6 Active→Final rows where `PermitStatus` had advanced to Complete ahead of `CaseStatus`, filled 5 `FINAL_DATE` values on those newly Final rows, and cleared 117 spurious `FINAL_DATE` values on non-Final rows. After repair: all Final rows have `FINAL_DATE` (960/960); Active/Final `PERMIT_DATE` coverage is 99.7% / 99.8%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover Austin through Waxahachie; **North Richland Hills** is the first without a script (2,000 sample rows).

## DATA schema

| INFERRED_SCHEMA | n |
| --- | ---: |
| `entity_core` (contacts, details, entity, fees, processing_status) | 1,737 |
| `entity_rich` (entity_core + attachments, holds, more_info, reviews) | 263 |

Both schemas share the same `entity` / `details` date and status fields. `CaseStatus` equals `PermitStatus` on 1,994 / 2,000 rows; the 6 mismatches are `Issued` / `Complete`. `processing_status` is present as a key but null on every sample row, so it is not used as a `FINAL_DATE` fallback.

Canonical sources:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | Prefer Final/Active on either `details.PermitStatus` or `entity.CaseStatus`; else map `CaseStatus` |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate`, else `details.IssueDate` |
| `FINAL_DATE` (Final only) | `entity.FinalDate`, else `details.FinalizeDate` |

Status map (portal → normalized): Complete / Closed / Finaled → Final; Issued / Active → Active; In Review / Submitted - Online / Fees Due / Fees Paid / On Hold / On Hold Awaiting New Documents / Resubmitted / Submittal Incomplete; Awaiting Additional Info. → In Review; Expired / Void / Denied / Withdrawn / Plan Approval Expired → Inactive.

## Findings by field

### STATUS_NORMALIZED

Before repair: Final 954 / Inactive 549 / Active 343 / In Review 131 / missing 23.

Portal `CaseStatus` inventory: Complete 954, Expired 421, Issued 343, Void 90, In Review 50, Submitted - Online 32, Fees Due 26, Denied 21, On Hold Awaiting New Documents 21, Fees Paid 16, Withdrawn 12, Plan Approval Expired 5, On Hold 5, Resubmitted 2, Submittal Incomplete; Awaiting Additional Info. 2.

- **23 FILLED:** previously unmapped hold / incomplete-submittal statuses → In Review.
- **6 FIXED:** `CaseStatus=Issued` but `PermitStatus=Complete` (plumbing / mechanical permits) had been left Active; promoted to Final because portal completion had already advanced.
- Remaining statuses already matched the map 1:1.

After: Final 960 / Inactive 549 / Active 337 / In Review 154 / missing 0.

### FILE_DATE

All 2,000 rows already had `FILE_DATE`, and every value matched `entity.ApplyDate` at calendar-day resolution. **0 FILLED / 0 FIXED.**

One pre-existing FILE>PERMIT quirk (`ApplyDate` after `IssueDate` by 7 days) is left as-is because both timestamps match DATA.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When `IssueDate` is present (1,727 rows), existing `PERMIT_DATE` already matches at calendar-day resolution → **0 FILLED / 0 FIXED**.
- **1 Active** and **2 Final** rows have `Issued=False` and null `IssueDate` → `PERMIT_DATE` stays missing (no issuance timestamp in DATA).
- Remaining missing `PERMIT_DATE` values are on In Review / Inactive rows where issuance never occurred, or Inactive rows that were never issued (expected).

After repair coverage: Active **336/337 (99.7%)**, Final **958/960 (99.8%)**. In Review 3.2%; Inactive 78.0% (Expired/Void/Denied/Withdrawn rows that were previously issued — expected).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All 954 originally Final (`Complete`) rows already had `FINAL_DATE` matching `FinalDate` / `FinalizeDate`.
- **5 FILLED** on the Issued→Final promotions that carried `FinalizeDate` (or `FinalDate`) in DATA but had null `FINAL_DATE` while still labeled Active.
- **117 FIXED** clears of spurious `FINAL_DATE` on non-Final rows: Inactive 105 (mostly Void/Denied/Withdrawn close stamps), Active 9 (Issued rows that still carry `FinalDate`), In Review 3 (Fees Paid / Submitted - Online / Resubmitted). Those rows retain `FinalDate` in DATA but should not carry a normalized finaled date.
- After repair every Final row has `FINAL_DATE` (**960/960**); Active / In Review / Inactive all 0%.
- Four Final rows keep portal `FinalDate` before `IssueDate` (PERMIT>FINAL=4); left as-is because both timestamps match DATA.

## Repair script

- Script: `agent/scripts/tx/data_repair_tx_north_richland_hills.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_north_richland_hills_repaired.parquet`

### Performance (sample n=2,000)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 23 | 6 | 23 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 273 → 273 |
| `FINAL_DATE` | 5 | 117 | 928 → 1,040 |

`FINAL_DATE` missing count rises because 117 spurious non-Final dates are cleared while only 5 Final dates are filled. Date-order violations after repair: FILE>PERMIT=1, PERMIT>FINAL=4, FILE>FINAL=0.
