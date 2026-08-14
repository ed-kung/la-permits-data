# Seminole (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Seminole. DATA is a uniform Tyler EnerGov payload (`entity` / `details` / `fees` / `processing_status`). `STATUS_NORMALIZED` and `FILE_DATE` were already correct on all 2,000 rows. Repair cleared 8 spurious In Review `PERMIT_DATE` values and 34 spurious non-Final `FINAL_DATE` values. Thirteen Final shells still lack `PERMIT_DATE` because DATA has no `IssueDate` (mostly Variance / Zoning Clearance).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-seen order. Seminole was the first pair without `agent/scripts/fl/data_repair_fl_seminole.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `energov_issued_finaled` | 1,696 |
| `energov_issued` | 193 |
| `energov_applied` | 82 |
| `energov_finaled` | 29 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) |
| FINAL_DATE | `entity.FinalDate` / `details.FinalizeDate`; else passed FINAL-ish `processing_status` inspection |

## Field assessments

### STATUS_NORMALIZED

Before/after: Final 1,633; Inactive 240; Active 84; In Review 43; **0 null**.

`CaseStatus` already matched the intended map (`Complete`→Final, `Issued`→Active, `Expired`/`Void`→Inactive, `On Hold`/`Submitted`/`Fees Invoiced`/`In Review`/`Submitted - Online`→In Review). No entity/details lag (`CaseStatus` equals `PermitStatus` on every row). Flags: **0 FILLED, 0 FIXED**.

### FILE_DATE

Missing on 0/2,000. Every row matches `entity.ApplyDate` (and `details.ApplyDate`) at UTC calendar-day resolution. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Before: missing 111. Present values already matched `entity.IssueDate` / `details.IssueDate`.

Repairs:

- **8** In Review rows with leftover `IssueDate` (7 On Hold, 1 In Review; `Issued=True`) → FIXED clear.

Not filled: 13 Final shells with `Issued=False` and blank `IssueDate` (6 Variance, 4 Zoning Clearance, 1 Photovoltaic, 1 Fence, 1 Re-Roof); 63 Inactive Void shells also lack `IssueDate`.

After: missing 119. Ideal Active/Final coverage 1,704/1,717 (99.2%). Flags: **0 FILLED, 8 FIXED**.

### FINAL_DATE

Before: present on all 1,633 Final rows (exact match to `entity.FinalDate` / `details.FinalizeDate`); also spuriously present on 5 Active, 27 Inactive, and 2 In Review.

Those non-Final `FinalDate` values are not true completions — Active examples often have `FinalDate` before `IssueDate`, and inspections are still open / requested. Cleared.

Repairs:

- **34** non-Final shells → FIXED clear.

After: Final 1,633/1,633 (100%); non-Final 0. Flags: **0 FILLED, 34 FIXED**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 8 | 111 → 119 |
| FINAL_DATE | 0 | 34 | 333 → 367 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_seminole.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_seminole_repaired.parquet`
