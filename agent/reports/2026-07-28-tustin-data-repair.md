# Tustin (CA) data repair

**Summary:** Assessed Tustin's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_tustin.py`. Tustin uses a Tyler EnerGov portal payload (`entity` + `details`). The repair fills 11 missing statuses and fixes 46 stale ones, fills 8 PERMIT_DATEs, fills 15 FINAL_DATEs on newly promoted Final rows, and clears 89 spurious FINAL_DATEs on non-Final rows. After repair, FILE_DATE is 100% populated, Final has 100% FINAL_DATE, and Active/Final have 98.5% / 96.0% PERMIT_DATE. Remaining PERMIT gaps are Closed/Finalized/Issued shells with null IssueDate in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Tustin, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,897 | `entity` + `details` + `contacts` + `fees` + `processing_status` |
| `entity_fees_reviews` | 103 | Above plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` → `STATUS_NORMALIZED` (with IssueDate / credible FinalDate overrides)
- `entity.ApplyDate` (fallback `details.ApplyDate`) → `FILE_DATE`
- `entity.IssueDate` (fallback `details.IssueDate`) → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`) → `FINAL_DATE`

`ExpireDate` is a validity window, not a completion date.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,332 / Inactive 299 / Active 217 / In Review 141 / missing 11.

Issues:

1. **Missing (11):** Almost all `STATUS_ORIGINAL == review approved` with CaseStatus `Review Approved` (unmapped upstream); one Issued and one Finalized row whose STATUS_ORIGINAL lagged.
2. **Incorrect / stale (46 after repair):** Finalized left Active/In Review; Closed left Inactive (STATUS_ORIGINAL `expired`); Issued left In Review; Expired left Active/In Review; Approved coded Active despite no IssueDate; Issued / Review Approved shells with FinalDate strictly after IssueDate (stale CaseStatus).

Repair performance: **11 FILLED, 46 FIXED**; missing after: **0**.

After: Final 1,353 / Inactive 299 / Active 194 / In Review 154.

Notable transitions: Active→In Review 16 (Approved without IssueDate); Active→Final 15 (Finalized labels + credible FinalDate on Issued); In Review→Active 8 (Issued / Submitted with IssueDate).

### FILE_DATE

Before: 0 missing. All 2,000 FILE_DATE values match `entity.ApplyDate` exactly.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 100%.

### PERMIT_DATE

Before: 292 missing. Where both present, PERMIT_DATE matches IssueDate exactly (1,708/1,708).

Repair: **8 FILLED** from IssueDate for Active/Final after status repair (stale In Review / missing-status Issued rows).

Remaining Active/Final gap: **57** (Closed 46, Finalized 8, Issued 3) — all lack IssueDate in DATA. Active coverage after repair: **191 / 194 (98.5%)**; Final: **1,299 / 1,353 (96.0%)**.

### FINAL_DATE

Before: 573 missing. All Final rows already had FINAL_DATE matching FinalDate/FinalizeDate. **89 non-Final rows** carried FINAL_DATE from junk workflow stamps (Issued/Approved with FinalDate ≤ IssueDate or no IssueDate; Expired/Void/Withdrawn closure stamps).

Repair: **15 FILLED** (status-promoted Final rows), **89 FIXED** (cleared spurious FINAL_DATE on non-Final).

Final coverage after repair: **1,353 / 1,353 (100%)**. No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_tustin.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky; Finalized/Closed → Final; FinalDate credible only if Finalized/Closed **or** FinalDate strictly after IssueDate (rejects Tustin's common junk FinalDate ≤ IssueDate stamps); else IssueDate → Active; else CaseStatus map (Approved / Review Approved → In Review).

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 11 | 46 | 11 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 8 | 0 | 292 | 284 |
| FINAL_DATE | 15 | 89 | 573 | 647 |

(Missing FINAL_DATE rises because 89 spurious non-Final stamps were cleared.)

Post-repair coverage by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- |
| Active (194) | 100% | 98.5% | 0% (expected) |
| Final (1,353) | 100% | 96.0% | 100% |
| In Review (154) | 100% | 0% | 0% (expected) |
| Inactive (299) | 100% | 75.6% | 0% (expected) |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_tustin.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_tustin_repaired.parquet`

## Not repairable from DATA

- 57 Active/Final rows with null IssueDate (mostly historical Closed shells) → PERMIT_DATE stays missing.
- A handful of agency chronology inversions already present in DATA (ApplyDate after IssueDate; IssueDate after FinalDate on Finalized rows) — dates copied as-is from authoritative fields.
- ExpireDate never used as FINAL_DATE.
