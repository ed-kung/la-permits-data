# Rancho Cordova (CA) data repair

**Summary:** Assessed Rancho Cordova's 1,999-row sample and wrote `agent/scripts/ca/data_repair_ca_rancho_cordova.py`. Rancho Cordova uses a Tyler EnerGov portal payload (`entity` + `details`). The repair fills 28 missing statuses and fixes 31 stale ones, fills 2 missing PERMIT_DATEs and 1 FINAL_DATE, and clears 9 spurious FINAL_DATEs on non-Final rows. After repair, FILE_DATE is 100% populated, Active has 99.1% PERMIT_DATE, Final has 98.2% PERMIT_DATE and 95.4% FINAL_DATE. Remaining Final FINAL gaps are almost all Admin Closed transportation permits and Recorded subdivision maps with null FinalDate in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Rancho Cordova, CA**.

## DATA schema

All 1,999 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,758 | `entity` + `details` + `contacts` + `fees` + `processing_status` |
| `entity_fees_reviews` | 241 | Above plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` → `STATUS_NORMALIZED` (with IssueDate / credible FinalDate overrides)
- `entity.ApplyDate` (fallback `details.ApplyDate`) → `FILE_DATE`
- `entity.IssueDate` (fallback `details.IssueDate`) → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`) → `FINAL_DATE`

`ExpireDate` is a validity window, not a completion date. `CompleteDate` / `ClosedDate` are always null in the sample.

## Findings by field

### STATUS_NORMALIZED

Before: Final 879 / Active 406 / In Review 358 / Inactive 328 / missing 28.

Issues:

1. **Missing (28):** 24 `Missing Information`, 1 `Field Acceptance`, 1 `In Punch List` (all pre-issuance → In Review); 1 `Warranty Accepted – Closeout Items Due` with FinalDate after IssueDate → Final; 1 same label without dates → In Review.
2. **Incorrect / stale (31 after repair):**
   - 6 `Issued` shells with FinalDate/FinalizeDate strictly after IssueDate (or PermitStatus `Final`) left Active → Final.
   - 3 In Review (`Fees Due` / `Fees Paid`) with FinalDate > IssueDate → Final.
   - 22 post-issuance `Fees Due` / `Fees Paid` / `On Hold` / `Warranty` / `Stop Work Order` / `Plan Approved` rows with IssueDate left In Review → Active.

Repair performance: **28 FILLED, 31 FIXED**; missing after: **0**.

After: Final 889 / Active 422 / In Review 360 / Inactive 328.

### FILE_DATE

Before: 0 missing. All 1,999 FILE_DATE values match `entity.ApplyDate` at calendar-day resolution.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 100%.

Note: 6 rows have ApplyDate after IssueDate in the agency payload (renewals / reopenings / timezone edge cases). The repair mirrors DATA and does not invent chronology.

### PERMIT_DATE

Before: 526 missing. Where both present, PERMIT_DATE matches IssueDate exactly (1,473/1,473).

Repair: **2 FILLED** (`Issued` Active Street Use / Encroachment shells with IssueDate but null PERMIT_DATE), **0 FIXED**.

Remaining Active/Final gap: **20** (Admin Closed 10, Recorded 5, In Construction 3, Issued 1, Final 1) — all lack IssueDate in DATA. Active coverage after repair: **418 / 422 (99.1%)**; Final: **873 / 889 (98.2%)**.

### FINAL_DATE

Before: 1,143 missing. Where both present, FINAL_DATE matches FinalDate exactly. **17 non-Final rows** carried FINAL_DATE; after status promotion, **9** still non-Final with junk stamps (Issued with FinalDate ≤ IssueDate; Expired / Void / Fees Due closure stamps) → cleared. One newly promoted Final (`Issued` with PermitStatus Final) had FinalizeDate but null FINAL_DATE → FILLED.

Repair: **1 FILLED, 9 FIXED** (cleared).

Final coverage after repair: **848 / 889 (95.4%)**. No spurious FINAL_DATE remains on Active / In Review / Inactive. Remaining 41 Final gaps: Admin Closed transportation/encroachment/repair shells (36) and Recorded Final Subdivision Maps (5) with null FinalDate/FinalizeDate in DATA.

## Repair script

`agent/scripts/ca/data_repair_ca_rancho_cordova.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky (Expired / Void / Denied / Plan Approval Expired); Final / Completed Project / Admin Closed / Recorded (CaseStatus or PermitStatus) → Final; FinalDate/FinalizeDate credible only if final label **or** stamp strictly after IssueDate; else IssueDate → Active; else CaseStatus map (Missing Information / Field Acceptance / In Punch List / Warranty / Stop Work / Fees Due / Fees Paid → In Review; In Construction → Active).

### Performance (n=1,999)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 28 | 31 | 28 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 2 | 0 | 526 | 524 |
| FINAL_DATE | 1 | 9 | 1,143 | 1,151 |

FINAL_DATE missing count rises slightly because 9 non-Final junk stamps were cleared while only 1 Final row was filled.

### Artifact

`AGENT_DATA_PATH/repaired/permits_ca_rancho_cordova_repaired.parquet`
