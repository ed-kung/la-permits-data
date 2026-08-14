# Palm Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Palm Beach. DATA is a uniform Tyler EnerGov payload (`entity` / `details` / `fees` / `holds` / empty `processing_status` / `reviews`). Repair upgraded 1 lagged Issued→Final shell and filled its `FINAL_DATE` from `FinalizeDate`, and cleared 9 spurious non-Final `FINAL_DATE` values. `FILE_DATE` and existing `PERMIT_DATE` values already matched DATA. 352 Active/Final shells still lack `PERMIT_DATE` because DATA has no `IssueDate` (mostly `Completed` administrative shells).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-seen order. Palm Beach was the first pair without `agent/scripts/fl/data_repair_fl_palm_beach.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `energov_full_issued_finaled` | 735 |
| `energov_full_issued` | 530 |
| `energov_full_applied` | 386 |
| `energov_full_finaled` | 349 |

All 2,000 rows share the same top-level key set. `processing_status` is always null; `reviews` / `more_info` / `attachments` are empty; `holds` is non-empty on 966 rows.

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) |
| FINAL_DATE | `entity.FinalDate` / `details.FinalizeDate` (inspection fallback unused — `processing_status` null) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,076; Active 411; Inactive 382; In Review 131; **0 null**.

Upstream mapping already matched DATA for every CaseStatus except one lag:

| CaseStatus | n | STATUS_NORMALIZED |
| --- | ---: | --- |
| Completed | 615 | Final |
| Final | 461 | Final |
| Issued | 411 | Active |
| Cancelled (trailing space in raw) | 245 | Inactive |
| Expired | 124 | Inactive |
| In Review | 78 | In Review |
| Submitted - Online | 48 | In Review |
| Abandoned | 8 | Inactive |
| Submitted | 5 | In Review |
| Denied | 4 | Inactive |
| Void | 1 | Inactive |

Repair: **1 FIXED** — `ROW-25-04218` has `CaseStatus=Issued` but `PermitStatus=Final` and `FinalizeDate=2025-07-06` (entity lags details) → Active→Final.

After: Final 1,077; Active 410; Inactive 382; In Review 131. Flags: **0 FILLED, 1 FIXED**.

### FILE_DATE

Missing on 0/2,000. Every row matches `entity.ApplyDate` at UTC calendar-day resolution. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Before missing: 735 (Final 348, Inactive 252, In Review 131, Active 4).

Where present, every value matches `entity.IssueDate` / `details.IssueDate`. In Review rows correctly have no `PERMIT_DATE` (and DATA has no `IssueDate`). Inactive gaps also lack `IssueDate` in DATA (Cancelled/Abandoned/Denied/Void never issued; only Expired and a few Cancelled carry issuance).

Not fillable:

- **339** `Completed` + **9** `Final` shells with `Issued=False` and blank `IssueDate` (still Final via FinalDate)
- **4** `Issued` Active shells with `Issued=False` and blank `IssueDate`

Flags: **0 FILLED, 0 FIXED**. After: Active 406/410 (99.0%); Final 729/1,077 (67.7%).

### FINAL_DATE

Before: present on 1,074/1,076 Final; also spuriously present on 5 Active and 4 Inactive (Copied from `FinalDate`/`FinalizeDate` while CaseStatus remained Issued/Cancelled).

Repairs:

- **1 FILLED** — lagged Issued→Final shell gets `FinalizeDate`
- **9 FIXED clear** — 5 Active + 4 Inactive spurious finals removed

After: Final 1,075/1,077 (99.8%); non-Final 0. Remaining 2 Final gaps are `Completed` shells (`REV-24-00570`, `REV-25-01042`) with blank `FinalDate` / `FinalizeDate` / `IssueDate` and null `processing_status`.

One Final row has `PERMIT_DATE` one calendar day after `FINAL_DATE` (agency stamp ordering); left as-is because both match DATA.

Flags: **1 FILLED, 9 FIXED**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 735 → 735 |
| FINAL_DATE | 1 | 9 | 917 → 925 |

Missing `FINAL_DATE` rises because 9 non-Final spurious values were cleared (net of 1 fill).

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_palm_beach.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_palm_beach_repaired.parquet`
