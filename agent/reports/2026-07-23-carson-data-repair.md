# Carson CA data repair

**Summary:** Carson’s 2,000 sample records use a Tyler EnerGov-style `entity` / `details` DATA payload (two key-set variants). The only systematic field error is missing `STATUS_NORMALIZED` for 293 rows whose `CaseStatus` values were never mapped upstream (`Additional Documents Required` × 291, `Planning Cleared` × 2); all are now `FILLED` → `In Review`. `FILE_DATE` is complete and matches `entity.ApplyDate`. `PERMIT_DATE` / `FINAL_DATE` already mirror `IssueDate` / `FinalDate` when present. Remaining gap: 46 Final (`Complete`/`Finaled`) rows lack `IssueDate` in DATA, so `PERMIT_DATE` cannot be filled. Repair script: `agent/scripts/data_repair_ca_carson.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Carson"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Carson, CA |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,293 |
| `entity_fees_reviews` | 707 |

Both schemas share `entity`, `details`, `contacts`, `fees`, `processing_status`. The richer variant adds `reviews` / `holds` / `attachments` / `more_info`.

Canonical date/status fields are under `entity` (with `details.PermitStatus` / `details.FinalizeDate` as identical or fallback mirrors). `STATUS_ORIGINAL` matches `entity.CaseStatus` 1:1 (case-insensitive).

## Field assessment

### STATUS_NORMALIZED — 293 missing, all fillable (293 FILLED / 0 FIXED)

Existing non-null mappings are consistent with `CaseStatus` and need no correction:

| CaseStatus | STATUS_NORMALIZED | n |
| --- | --- | --- |
| Issued | Active | 806 |
| Complete | Final | 128 |
| Finaled | Final | 113 |
| Void | Inactive | 115 |
| Expired | Inactive | 6 |
| Denied | Inactive | 3 |
| In Review / Fees Due / Fees Paid / On Hold / Submitted / Submitted - Online / Ready For Review | In Review | 536 |

Upstream left these unmapped (`STATUS_NORMALIZED` null):

| CaseStatus | Repair → | n |
| --- | --- | --- |
| Additional Documents Required | In Review | 291 |
| Planning Cleared | In Review | 2 |

After repair: 0 missing statuses. Distribution: In Review 829, Active 806, Final 241, Inactive 124.

A handful of non-Final rows carry `entity.FinalDate` while `CaseStatus` remains `Issued` / `Fees Due` / `Additional Documents Required` (4 rows). Status is left aligned to `CaseStatus` (same convention as other EnerGov cities); those anomalous final dates are noted under FINAL_DATE.

### FILE_DATE — correct (0 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- All 2,000 rows populated; every value equals the UTC calendar date of `entity.ApplyDate` (also present as `details.ApplyDate`).
- `OpenedDate` / `RequestDate` / `CompleteDate` / `ClosedDate` / `StartDate` are universally null in this sample.
- Repair re-derives from `ApplyDate` for robustness but changes nothing on the sample.

### PERMIT_DATE — correct where `IssueDate` exists; 46 Final unfillable (0 FILLED / 0 FIXED)

- Ideal: populated for Active and Final.
- When present, `PERMIT_DATE` always matches `entity.IssueDate` (1,015 / 1,015). `details.IssueDate` matches whenever entity has it.
- Active: 806 / 806 (100%) have `PERMIT_DATE`.
- Final: 195 / 241 (80.9%) have `PERMIT_DATE`.
- The 46 gaps (45 `Complete`, 1 `Finaled`) have null `IssueDate` and `details.Issued == False`. Most are miscellaneous applications or address assignments that were marked Complete without a formal issuance. `FILE_DATE` is not used as a proxy.
- Remaining missing dates are mostly In Review / pre-issuance Inactive rows, where absence is expected. A few In Review / Inactive rows do have `IssueDate` (and matching `PERMIT_DATE`) when the agency recorded issuance before a later status change (e.g. Expired, Void, Fees Due).

### FINAL_DATE — correct for Final (0 FILLED / 0 FIXED)

- Ideal: populated for Final.
- All 241 Final rows have `FINAL_DATE`, matching `entity.FinalDate` (and `details.FinalizeDate`).
- No Final row is missing a recoverable final date; `CompleteDate` / `ClosedDate` are always null.
- Four non-Final rows also carry `FinalDate` in DATA (and in the column): 2 Active (`Issued`, one with a passed final inspection), 1 In Review (`Fees Due`), 1 formerly-null status (`Additional Documents Required`). Left as-is; status remains driven by `CaseStatus`.

## Repair function

`agent/scripts/data_repair_ca_carson.py` → `data_repair(df)`

- Overwrites incorrect / missing fields from DATA
- Adds `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`} and `INFERRED_SCHEMA`
- CLI preview on the LA sample:

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 293 | 0 | 293 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 985 → 985 |
| FINAL_DATE | 0 | 0 | 1,755 → 1,755 |

## Artifacts

- `agent/scripts/data_repair_ca_carson.py`
- `agent/reports/2026-07-23-carson-data-repair.md`
