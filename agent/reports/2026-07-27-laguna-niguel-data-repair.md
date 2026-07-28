# Laguna Niguel (CA) data repair

**Summary:** Laguna Niguel was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from two DATA families (civic-portal `permit_info` and Tyler EnerGov `entity`). Status is now fully populated (**FILLED 1**): `APPLIED-ONLINE` was left null. `FILE_DATE` already matched Applied/ApplyDate for all 2,000 rows. `PERMIT_DATE` missingness fell from **775 → 772** (**FILLED 3**), using `PermitApprovedDate` when Issued was blank on Active/Final rows. The main defect was **708 spurious `FINAL_DATE` values**: 701 In Review rows copied the portal sentinel `1/1/1900`, and 7 Inactive rows carried EXPIRED / Plan Approval Expired close stamps — all cleared (**FIXED 708**). After repair, every Final row has `FINAL_DATE`, and Active/Final `PERMIT_DATE` coverage is 100% / 99.7%.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Laguna Niguel, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_laguna_niguel.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/laguna_niguel_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 945 | Issued + Finaled present (sentinel `1/1/1900` treated as blank) |
| `permit_info_applied_only` | 743 | Only Applied populated (includes 701 former APPLIED+1900-finaled rows) |
| `permit_info_issued` | 194 | Issued present, Finaled blank |
| `entity` | 75 | EnerGov entity/details/fees without reviews |
| `entity_reviews` | 34 | entity plus reviews/holds/attachments/more_info |
| `permit_info_finaled_only` | 5 | Finaled present, Issued blank |
| `permit_info_approved_only` | 4 | Approved present, Issued/Finaled blank |

Canonical fields:

| Field | `permit_info` source | `entity` source |
| --- | --- | --- |
| `STATUS_NORMALIZED` | `PermitStatus` | `CaseStatus` / `details.PermitStatus` |
| `FILE_DATE` | `PermitAppliedDate` | `ApplyDate` |
| `PERMIT_DATE` | `PermitIssuedDate`, else `PermitApprovedDate` | `IssueDate` |
| `FINAL_DATE` | `PermitFinaledDate` (reject year ≤ 1900) | `FinalDate` / `FinalizeDate` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 971 · In Review 728 · Inactive 197 · Active 103 · missing 1

Both schemas mapped cleanly from source status. Only gap:

| Change | n | Reason |
| --- | ---: | --- |
| APPLIED-ONLINE: null → In Review | 1 | Unmapped `STATUS_ORIGINAL` / `PermitStatus` |

Upstream already aligned Final↔FINALED/Finaled/Complete, Active↔ISSUED/Issued/APPROVED, Inactive↔EXPIRED/VOID/WITHDRAWN/etc., In Review↔APPLIED/Submitted/Plan Check/Fees Due/etc.

**After:** Final 971 · In Review 729 · Inactive 197 · Active 103 · missing 0  
Flags: **FILLED 1 · FIXED 0**

### FILE_DATE

**Before:** 0 missing (100%).

- All `permit_info` rows match `PermitAppliedDate`.
- All `entity` rows match `ApplyDate` (calendar-day).

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 775 missing (38.8%). Among Active/Final: 6 / 1,074 missing.

Root cause: upstream skipped rows where `PermitIssuedDate` was blank even when `PermitApprovedDate` was available. Remaining Active/Final gaps have neither Issued nor Approved in DATA.

Repairs (Active / Final only):
1. Prefer `PermitIssuedDate` / entity `IssueDate`.
2. Else `PermitApprovedDate`.

**After:** 772 missing. Active 103/103 (100%); Final 968/971 (99.7%).  
Flags: **FILLED 3 · FIXED 0**

Not repairable: 3 Final `FINALED` rows with blank Issued and Approved (still have `PermitFinaledDate`).

### FINAL_DATE

**Before:** 321 missing. Among Final: 0 / 971 missing (100%). But 701 In Review and 7 Inactive rows incorrectly carried `FINAL_DATE`.

Root causes:
1. Civic portal uses `PermitFinaledDate = "1/1/1900"` as a blank placeholder on APPLIED permits; upstream copied it as a real date.
2. Inactive EXPIRED / Plan Approval Expired rows had close/approval-expire stamps in Finaled/FinalDate that are not true permit finaling.

Repairs:
1. Treat year ≤ 1900 as missing when reading source dates.
2. Clear `FINAL_DATE` on any non-Final row.
3. For Final rows, keep / set from `PermitFinaledDate` or entity `FinalDate`/`FinalizeDate` (already complete in sample).

**After:** 1,029 missing (expected: only non-Final rows lack FINAL_DATE). Final 971/971 (100%); Active / In Review / Inactive 0%.  
Flags: **FILLED 0 · FIXED 708**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 1 | 0 | 1 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 3 | 0 | 775 → 772 |
| `FINAL_DATE` | 0 | 708 | 321 → 1,029 |

`FINAL_DATE` missingness rises because incorrect non-Final values were removed; coverage for Final remains 100%.
