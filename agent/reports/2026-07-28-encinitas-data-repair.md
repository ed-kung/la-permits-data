# Encinitas (CA) data repair

**Summary:** Assessed Encinitas's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_encinitas.py`. Encinitas uses a Tyler EnerGov portal payload (`entity` + `details`). The repair fixes 12 stale statuses, fills 1 FINAL_DATE on a newly promoted Final row, and clears 62 spurious FINAL_DATEs on non-Final rows. After repair, FILE_DATE is 100% populated, Active has 100% PERMIT_DATE, Final has 99.6% PERMIT_DATE and 99.8% FINAL_DATE. Remaining gaps are Finaled shells with null IssueDate / FinalDate in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Encinitas, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,683 | `entity` + `details` + `contacts` + `fees` + `processing_status` |
| `entity_basic` | 168 | Same without `fees` |
| `entity_fees_reviews` | 149 | `entity_fees` plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` → `STATUS_NORMALIZED` (with IssueDate / credible FinalDate overrides)
- `entity.ApplyDate` (fallback `details.ApplyDate`) → `FILE_DATE`
- `entity.IssueDate` (fallback `details.IssueDate`) → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`) → `FINAL_DATE`

`ExpireDate` is a validity window, not a completion date. `CompleteDate` / `ClosedDate` / `OpenedDate` are unused (always null in the sample). `processing_status` is always null.

## Findings by field

### STATUS_NORMALIZED

Before: Final 564 / Inactive 545 / Active 526 / In Review 365 / missing 0.

`STATUS_ORIGINAL` matches `entity.CaseStatus` for every row. The original CaseStatus → STATUS_NORMALIZED map is internally consistent (Issued→Active, Finaled→Final, Expired/Void/Abandoned/Withdrawn/Denied→Inactive, review-pipeline labels→In Review). Issues are stale labels relative to dates / PermitStatus:

1. **Issued + PermitStatus Finaled (1):** `MEPR-036251-2025` left Active despite FinalizeDate → FIXED to Final.
2. **Issued with FinalDate strictly after IssueDate (1):** `MEPR-026074-2023` left Active → FIXED to Final.
3. **In Review with IssueDate (10):** Pending Payment (5), Under Review Short-Term Rentals (4), Ready To Issue (1) left In Review despite IssueDate → FIXED to Active (8) or Final (2, when FinalDate > IssueDate).

Repair performance: **0 FILLED, 12 FIXED**; missing after: **0**.

After: Final 568 / Inactive 545 / Active 532 / In Review 355.

### FILE_DATE

Before: 0 missing. All 2,000 FILE_DATE values match `entity.ApplyDate` at calendar-day resolution. (Some `details.ApplyDate` values differ by a Pacific/UTC offset and occasionally cross midnight; entity is the canonical source.)

Repair: **0 FILLED, 0 FIXED**. Coverage remains 100%.

### PERMIT_DATE

Before: 476 missing. Where both present, PERMIT_DATE matches IssueDate exactly (1,524/1,524). No IssueDate present with missing PERMIT_DATE.

Repair: **0 FILLED, 0 FIXED** — rows that gained Active/Final status via repair already carried PERMIT_DATE from IssueDate.

Remaining Active/Final gap: **2** Finaled shells with null IssueDate (`BLDR-009389-2020` ADU; `FLSALRM-006582-2016` False Alarm). Active coverage after repair: **532 / 532 (100%)**; Final: **566 / 568 (99.6%)**.

One Inactive Abandoned row has IssueDate one calendar day before ApplyDate (agency chronology quirk); left as-is.

### FINAL_DATE

Before: 1,372 missing. Where both present, FINAL_DATE matches FinalDate exactly (628/628). One Issued/Finaled shell (`MEPR-036251-2025`) had FinalizeDate but null entity.FinalDate and null FINAL_DATE.

**65 non-Final rows** carried FINAL_DATE from junk / case-closure stamps:

- 59 Inactive (mostly Expired; also Void / Abandoned) — FinalDate is a closure stamp, not a finaled date
- 3 Active Issued (2 with FinalDate ≤ IssueDate; 1 promoted to Final and kept)
- 3 In Review Pending Payment (2 promoted to Final and kept; 1 with FinalDate but no IssueDate left In Review and cleared)

One Finaled shell (`BLDR-032145-2024` Demolition Residential) has null FinalDate and null FinalizeDate → cannot fill.

Repair: **1 FILLED** (FinalizeDate on Issued/Finaled), **62 FIXED** (cleared spurious FINAL_DATE on non-Final).

Final coverage after repair: **567 / 568 (99.8%)**. No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_encinitas.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky (Expired / Void / Withdrawn / Denied / Abandoned); Finaled from CaseStatus **or** PermitStatus → Final; FinalDate/FinalizeDate credible only if Finaled **or** stamp strictly after IssueDate; else IssueDate → Active; else CaseStatus map (Under Review / eSubmitted / Pending Payment / Waiting For Files / Ready To Issue / Applicant Action Required / On Hold → In Review).

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 12 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 476 | 476 |
| FINAL_DATE | 1 | 62 | 1,372 | 1,433 |

Missing FINAL_DATE rises because 62 spurious non-Final stamps were cleared (net of 1 fill). Ideal-coverage after repair: FILE 100%; Active PERMIT 100%; Final PERMIT 99.6%; Final FINAL 99.8%.

### Artifact

`AGENT_DATA_PATH/repaired/permits_ca_encinitas_repaired.parquet`
