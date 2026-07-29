# Victorville (CA) data repair

**Summary:** Assessed Victorville's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_victorville.py`. Victorville uses a Tyler EnerGov portal payload (`entity` + `details`). The repair fixes 33 stale statuses (mostly Issued/Inspection shells with post-issue final stamps left Active), fills 3 FINAL_DATEs on newly promoted Final rows from `FinalizeDate`, and clears 9 spurious FINAL_DATEs on non-Final rows. After repair, FILE_DATE is 100% populated, Active has 92.1% PERMIT_DATE, Final has 98.5% PERMIT_DATE and 90.2% FINAL_DATE. Remaining gaps lack IssueDate / FinalDate in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Victorville, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,969 | `entity` + `details` + `contacts` + `fees` + `processing_status` |
| `entity_fees_reviews` | 31 | Above plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` → `STATUS_NORMALIZED` (with IssueDate / credible FinalDate overrides)
- `entity.ApplyDate` (fallback `details.ApplyDate`) → `FILE_DATE`
- `entity.IssueDate` (fallback `details.IssueDate`) → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`) → `FINAL_DATE`

`ExpireDate` is a validity window, not a completion date. `CompleteDate` / `ClosedDate` / `OpenedDate` are unused (always null in the sample). `CaseStatus` and `PermitStatus` agree on 1,997/2,000 rows; the 3 disagreements are `Issued`/`Finaled`.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,354 / Inactive 287 / Active 263 / In Review 96 / missing 0.

Raw `CaseStatus` distribution maps cleanly in most cases (`Finaled`→Final, `Issued`/`Inspection`→Active, `Expired`/`Void`/`Denied`→Inactive, `Submitted`/`In Review`/`Corrections Required`/`Plan Approved`→In Review). Issues:

1. **Stale Active (28):** 19 `Inspection` and 6 `Issued` shells carry `FinalDate`/`FinalizeDate` strictly after `IssueDate` but were left Active; plus 3 `Issued` shells whose `PermitStatus` is already `Finaled` (FinalizeDate present, entity.FinalDate null). → FIXED to Final.
2. **Stale In Review (5):** 4 `Submitted`/`Corrections Required` rows with `IssueDate` left In Review → FIXED to Active; 1 `Submitted` row (`HAZ11-00015`) with IssueDate and FinalDate after IssueDate → FIXED to Final.

Inactive labels (`Expired` / `Void` / `Denied`) are sticky even when FinalDate is present as a case-closure stamp.

Repair performance: **0 FILLED, 33 FIXED**; missing after: **0**.

After: Final 1,383 / Inactive 287 / Active 239 / In Review 91.

### FILE_DATE

Before: 0 missing. All 2,000 FILE_DATE values match `entity.ApplyDate` exactly.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 100%.

### PERMIT_DATE

Before: 237 missing. Where both present, PERMIT_DATE matches IssueDate exactly (1,763/1,763). No spurious PERMIT_DATE on non-issued In Review rows after status repair (the 5 In Review rows that had PERMIT_DATE were correctly promoted to Active/Final).

Repair: **0 FILLED, 0 FIXED** — status-promoted rows already carried PERMIT_DATE from IssueDate.

Remaining Active/Final gap: **40** (Issued 19, Finaled 21) — all lack IssueDate in DATA. Active coverage after repair: **220 / 239 (92.1%)**; Final: **1,362 / 1,383 (98.5%)**.

### FINAL_DATE

Before: 746 missing. Where both present, FINAL_DATE matches FinalDate exactly. Three Issued/`PermitStatus=Finaled` shells had FinalizeDate but null entity.FinalDate and null FINAL_DATE. **35 non-Final rows** carried FINAL_DATE from workflow stamps (19 Inspection + 8 Issued with FinalDate; 7 Inactive Void/Expired closure stamps; 1 In Review Submitted).

Of those 35, 29 were status-promoted to Final (keeping or filling FINAL_DATE). The remaining 9 (2 Issued with FinalDate ≤ IssueDate; 7 Inactive) had FINAL_DATE cleared.

Repair: **3 FILLED** (Issued/`Finaled` shells from FinalizeDate), **9 FIXED** (cleared spurious FINAL_DATE on non-Final).

Final coverage after repair: **1,248 / 1,383 (90.2%)**. The 135 still-missing Final rows are all `CaseStatus=Finaled` with null FinalDate and null FinalizeDate in DATA. No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_victorville.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky (Expired / Void / Denied); Finaled/Complete from CaseStatus **or** PermitStatus → Final; FinalDate/FinalizeDate credible only if Finaled/Complete **or** stamp strictly after IssueDate; else IssueDate → Active; else CaseStatus map (Submitted / Corrections Required / Plan Approved / In Review → In Review; Issued / Inspection → Active).

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 33 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 237 | 237 |
| FINAL_DATE | 3 | 9 | 746 | 752 |

Status transitions: Active→Final 28; In Review→Active 4; In Review→Final 1.

Ideal coverage after repair: FILE_DATE 100%; Active PERMIT_DATE 92.1%; Final PERMIT_DATE 98.5%; Final FINAL_DATE 90.2%. Two pre-existing FILE>PERMIT chronology inversions remain in DATA (not introduced by repair).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_victorville.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_victorville_repaired.parquet`
