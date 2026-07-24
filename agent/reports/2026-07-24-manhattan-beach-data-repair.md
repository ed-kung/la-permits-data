# Manhattan Beach CA data repair

**Summary:** Manhattan Beach’s 2,000 sample records are Tyler EnerGov payloads (`entity` / `details` / `fees`, with an optional reviews bundle). Upstream already maps `CaseStatus` correctly and dates already match `entity` when present: `FILE_DATE` is complete (100%), Active/Final are nearly complete for `PERMIT_DATE` (99.3% / 99.7%), and Final rows are nearly complete for `FINAL_DATE` (99.8%). The only material defect is **145 non-Final rows with spurious `FINAL_DATE`** copied from `entity.FinalDate` (Void, Withdrawn, Expired, History, Issued, In Review, Partial Fees Paid) → cleared as FIXED. Script: `agent/scripts/data_repair_ca_manhattan_beach.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Manhattan Beach"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Manhattan Beach, CA (after Alhambra … La Cañada Flintridge / La Habra / Lancaster / Lomita / Long Beach / Los Angeles / Los Angeles County; La Cañada already covered by `data_repair_ca_la_canada_flintridge.py`) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,923 |
| `entity_fees_reviews` | 77 |

Canonical fields under `entity` (details used as fallback):

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate` |
| `FINAL_DATE` | `entity.FinalDate` (fallback `details.FinalizeDate`, Final status only) |

`ExpireDate` is a validity window, not a completion date. `CaseStatus` is authoritative over `details.PermitStatus` (one Issued row has stale `PermitStatus=Finaled` with `FinalizeDate` but null `entity.FinalDate` → left Active).

Status map: Finaled / Closed → Final; Issued → Active; Expired / Plan Approval Expired / Void / Withdrawn / History / Denied → Inactive; In Review / Fees Due / Fees Paid / Partial Fees Paid / Submitted / Submitted - Online / Incomplete Submittal / On Hold / Pending Workflow Requirements / Ready To Issue → In Review.

## Field assessment

### STATUS_NORMALIZED — 0 missing; 0 incorrect

Every `STATUS_ORIGINAL` equals `entity.CaseStatus`, and the existing normalized mapping already matches the map above for all 19 CaseStatus values in the sample. No FILLED / FIXED.

Distribution (unchanged): Final 1,028; Inactive 427; Active 423; In Review 122.

### FILE_DATE — complete and correct

- Ideal: application / submittal date for all records.
- 2,000 / 2,000 match the UTC calendar day of `entity.ApplyDate` (0 mismatches, 0 missing).
- No FILLED / FIXED.

### PERMIT_DATE — correct when present; 6 Active/Final unfillable

- Ideal: populated for Active and Final.
- Where both `PERMIT_DATE` and `IssueDate` exist, UTC day always matches (0 mismatches).
- Missing before repair: Active 3/423, Final 3/1,028, In Review 109/122, Inactive 126/427.
- The 6 Active/Final gaps all have null `IssueDate` and `details.Issued=False` (3 Issued, 2 Finaled, 1 Closed). No safe proxy in DATA → left missing.

After repair (unchanged): Active 420/423 (99.3%), Final 1,025/1,028 (99.7%).

### FINAL_DATE — Final rows correct; 145 spurious on non-Final

- Ideal: populated for Final.
- 1,026 / 1,028 Final rows already match `entity.FinalDate` (= `details.FinalizeDate` when both present).
- 2 Final rows lack both `FinalDate` and `FinalizeDate` (one Finaled mechanical permit, one Closed ROW storage) → cannot fill.
- 145 non-Final rows carried `FINAL_DATE` from `entity.FinalDate`:
  - Inactive 131 (Void×72, Withdrawn×29, Expired×23, History×7)
  - In Review 11 (In Review×10, Partial Fees Paid×1)
  - Active 3 (Issued with FinalDate present)
  - Many History / In Review kitchen-bath remodel rows have `FinalDate` ≈ ApplyDate + 1 year (= ExpireDate pattern), reinforcing that these are not true sign-offs under non-Final CaseStatus.
- Cleared as FIXED — same convention as Hawthorne / Glendale.

After repair: Final 1,026/1,028 (99.8%); Active / In Review / Inactive have none.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 0 | 0 | 0 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 241 → 241 |
| `FINAL_DATE` | 0 | 145 | 829 → 974 |

Missing `FINAL_DATE` rises because 145 non-Final spurious values are cleared; among Final rows coverage remains 1,026 / 1,028 (99.8%).

| STATUS_NORMALIZED | Before | After |
| --- | --- | --- |
| Final | 1,028 | 1,028 |
| Inactive | 427 | 427 |
| Active | 423 | 423 |
| In Review | 122 | 122 |

## Artifacts

- Repair script: `agent/scripts/data_repair_ca_manhattan_beach.py`
- Function: `data_repair(df)` → adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` columns (`FILLED` / `FIXED`)
