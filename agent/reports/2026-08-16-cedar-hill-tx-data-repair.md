# Cedar Hill (TX) data repair

**Summary:** Cedar Hill was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Carrollton). All 2,001 rows are CivicPlus / EnerGov `entity_rich` payloads. STATUS_NORMALIZED lagged the live portal status on 24 rows (23 Issued→Complete still Active; 1 Issued→Void still Active). FILE_DATE already matches `ApplyDate` on every row; PERMIT_DATE needed no fills (remaining gaps are `2999-01-01` IssueDate sentinels). Repair filled 23 missing FINAL_DATE values on newly Final rows from `FinalizeDate`/`FinalDate`, and cleared 28 spurious FINAL_DATE values on Active (Issued) rows. After repair: Active PERMIT_DATE 97.7%; Final FINAL_DATE 99.2%.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Cedar Hill, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_cedar_hill.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_cedar_hill_repaired.parquet`

## DATA schema

EnerGov-style nested object. Every sample row shares the same top-level keys:

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_rich | 2,001 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `details.PermitStatus` when Complete; else `entity.CaseStatus` | — |
| FILE_DATE | `entity.ApplyDate` | — |
| PERMIT_DATE | `entity.IssueDate` | — |
| FINAL_DATE | `entity.FinalDate` | `details.FinalizeDate` |

`CaseStatus` and `PermitStatus` agree on 1,981 / 2,001 rows. The 20 disagreements are `CaseStatus=Issued` with `PermitStatus=Complete`; those rows all carry a real `details.FinalizeDate`, so Complete is treated as authoritative.

Portal sentinels: `2999-01-01` on IssueDate / FinalDate / FinalizeDate is treated as missing (year outside 1900–2035).

## Field assessment

### STATUS_NORMALIZED

No missing values. Normalized status was built from lagged `STATUS_ORIGINAL`, so 24 rows disagree with live CaseStatus / PermitStatus:

| Portal status | Prior STATUS_NORMALIZED | Corrected | n |
| --- | --- | --- | ---: |
| PermitStatus Complete (CaseStatus Issued) | Active | Final | 20 |
| CaseStatus Complete | Active | Final | 3 |
| CaseStatus Void | Active | Inactive | 1 |

All 24 had `STATUS_ORIGINAL=issued`. Mapping otherwise: Issued→Active, Complete→Final, Expired / Void / Denied / Plan Approval Expired→Inactive, In Review / Submitted / Submitted - Online / On Hold / Stop Work Order→In Review.

### FILE_DATE

Fully populated (0 missing). Every row matches `entity.ApplyDate` at calendar-day resolution (0 FILLED, 0 FIXED).

### PERMIT_DATE

95 missing before and after repair (0 FILLED, 0 FIXED). Existing non-null PERMIT_DATE values already match `entity.IssueDate`. Unfillable gaps:

- 27 Active rows with IssueDate sentinel `2999-01-01` (details.Issued=True but no real issuance timestamp)
- 1 Final row with sentinel IssueDate
- Remaining gaps are pre-issuance In Review / terminal Inactive (Void, Denied, Plan Approval Expired) with null IssueDate

After status repair: Active 1,134 / 1,161 (97.7%); Final 523 / 524 (99.8%).

### FINAL_DATE

1,476 missing before repair. Issues:

1. **Under-filled Final:** 20 Issued→Complete and 3 Complete rows remapped to Final had null FINAL_DATE but a usable FinalizeDate or FinalDate → FILLED (23).
2. **Spurious Active FINAL_DATE:** 28 Issued/Active rows carried a portal FinalDate (18 equal to IssueDate; 10 differed) while status was still Issued → FIXED (cleared).
3. **Unfillable Final:** 4 Complete rows have FinalDate / FinalizeDate sentinel `2999-01-01` → FINAL_DATE stays missing.

After repair: Final 520 / 524 (99.2%); non-Final all empty.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 24 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 95 → 95 |
| FINAL_DATE | 23 | 28 | 1,476 → 1,481 |

STATUS_NORMALIZED after repair: Active 1,161; Final 524; Inactive 276; In Review 40.

After repair, by status:

- **FILE_DATE:** 2,001 / 2,001 (100%)
- **PERMIT_DATE:** Active 1,134 / 1,161 (97.7%); Final 523 / 524 (99.8%)
- **FINAL_DATE:** Final 520 / 524 (99.2%); non-Final remain empty

Date-order violations (FILE>PERMIT) remain 33 before and after; they are pre-existing ApplyDate / IssueDate inversions in the portal payload, not introduced by repair. PERMIT>FINAL and FILE>FINAL are 0 after repair.
