# El Cajon (CA) data repair

**Summary:** Assessed El Cajon's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_el_cajon.py`. El Cajon uses a Tyler EnerGov portal payload (`entity` + `details`). The repair fills 9 missing statuses and fixes 55 stale ones, fills 37 FINAL_DATEs on newly promoted Final rows, and clears 134 spurious FINAL_DATEs on non-Final rows. After repair, FILE_DATE is 100% populated, Final has 100% FINAL_DATE, and Active has 96.4% PERMIT_DATE. Remaining PERMIT gaps are mostly Complete Encroachment shells and Issued shells with null IssueDate in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **El Cajon, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,831 | `entity` + `details` + `contacts` + `fees` + `processing_status` |
| `entity_fees_reviews` | 169 | Above plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` → `STATUS_NORMALIZED` (with IssueDate / credible FinalDate overrides)
- `entity.ApplyDate` (fallback `details.ApplyDate`) → `FILE_DATE`
- `entity.IssueDate` (fallback `details.IssueDate`) → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`) → `FINAL_DATE`

`ExpireDate` is a validity window, not a completion date. `CompleteDate` / `ClosedDate` are unused (always null in the sample).

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,054 / Active 435 / Inactive 381 / In Review 121 / missing 9.

Issues:

1. **Missing (9):** 7 `OFC` (no IssueDate; treated as In Review), 1 `Fees Due (Post-Issuance)` (has IssueDate → Active), 1 `Not Accepted - emailed missing information` → Inactive.
2. **Incorrect / stale (55 after repair):**
   - 35 `Issued` shells whose `details.PermitStatus` is `Complete` (FinalizeDate present) left Active → Final.
   - 2 `Issued` shells with FinalDate strictly after IssueDate left Active → Final.
   - 14 post-issuance `Fees Due` / `Fees Paid` / `On Hold` / `Pending` rows with IssueDate left In Review → Active.
   - 4 In Review rows (Fees Paid with Complete PermitStatus or FinalDate > IssueDate) → Final.

Repair performance: **9 FILLED, 55 FIXED**; missing after: **0**.

After: Final 1,095 / Active 413 / Inactive 382 / In Review 110.

### FILE_DATE

Before: 0 missing. All 2,000 FILE_DATE values match `entity.ApplyDate` exactly.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 100%.

### PERMIT_DATE

Before: 686 missing. Where both present, PERMIT_DATE matches IssueDate exactly (1,314/1,314).

Repair: **0 FILLED, 0 FIXED** — rows that gained Active/Final status via repair already carried PERMIT_DATE from IssueDate, and the one newly filled Active (`Fees Due (Post-Issuance)`) already had PERMIT_DATE populated.

Remaining Active/Final gap: **448** (Complete 432, Issued 15, Closed 1) — all lack IssueDate in DATA. Nearly all Complete-without-IssueDate rows are Encroachment Permit Application cases that final without an issuance stamp. Active coverage after repair: **398 / 413 (96.4%)**; Final: **662 / 1,095 (60.5%)**.

### FINAL_DATE

Before: 808 missing. All Final rows already had FINAL_DATE matching FinalDate. **134 non-Final rows** carried FINAL_DATE from junk workflow stamps (Issued with FinalDate ≤ IssueDate; Inactive Plan Approval Expired / Void / Canceled closure stamps; In Review Fees Due / Resubmittal / Pending stamps). Separately, 37 Issued/Fees Paid shells with `PermitStatus=Complete` had FinalizeDate but null entity.FinalDate and null FINAL_DATE.

Repair: **37 FILLED** (status-promoted Final rows from FinalizeDate), **134 FIXED** (cleared spurious FINAL_DATE on non-Final).

Final coverage after repair: **1,095 / 1,095 (100%)**. No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_el_cajon.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky (including Plan Approval Expired / Rejected / Not Accepted); Complete/Closed/Finaled from CaseStatus **or** PermitStatus → Final; FinalDate/FinalizeDate credible only if Complete/Closed/Finaled **or** stamp strictly after IssueDate; else IssueDate → Active; else CaseStatus map (OFC / Fees Due / Fees Paid / Submitted → In Review; Fees Due (Post-Issuance) → Active).

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 9 | 55 | 9 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 686 | 686 |
| FINAL_DATE | 37 | 134 | 808 | 905 |

Missing FINAL_DATE rises because junk stamps on non-Final rows are cleared (ideal for Active/In Review/Inactive).

### Coverage after repair

| Check | Result |
| --- | --- |
| FILE_DATE present | 2,000 / 2,000 (100%) |
| PERMIT_DATE on Active | 398 / 413 (96.4%) |
| PERMIT_DATE on Final | 662 / 1,095 (60.5%) |
| FINAL_DATE on Final | 1,095 / 1,095 (100%) |
| FINAL_DATE on non-Final | 0 |

Pre-existing chronology quirks in agency DATA (not introduced by repair): 56 FILE>PERMIT (often Jan-1 IssueDate on annual licenses applied later) and 6 PERMIT>FINAL on Complete tobacco/license shells.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_el_cajon.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_el_cajon_repaired.parquet`
