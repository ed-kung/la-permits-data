# La Cañada Flintridge CA data repair

**Summary:** La Cañada Flintridge’s 2,000 sample records are Tyler EnerGov-style payloads (`entity` / `details` / `fees`, optionally with `reviews`). `FILE_DATE` is already complete and matches `entity.ApplyDate`. Material repairs: fill 164 missing `STATUS_NORMALIZED` values from five unmapped pre-issuance CaseStatus labels → In Review; clear 229 spurious `FINAL_DATE` values on non-Final rows (Void/Withdrawn close stamps and Issued rows still open in EnerGov). `PERMIT_DATE` already matches `IssueDate` wherever both exist; 2 Final rows lack any issuance date in DATA and remain missing. Script: `agent/scripts/data_repair_ca_la_canada_flintridge.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "La Cañada Flintridge"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | La Cañada Flintridge, CA (after Alhambra … Hermosa Beach / Inglewood) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,813 |
| `entity_fees_reviews` | 187 |

Canonical fields from the EnerGov `entity` schema:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate` |
| `FINAL_DATE` | `entity.FinalDate` (fallback `details.FinalizeDate`) |

Status map: Complete → Final; Issued → Active; Void / Expired / Withdrawn / Plan Approval Expired → Inactive; In Review / In Plan Check / In Screening / On Hold / Submitted / Submitted - Online / Pending Invoice Payment / Pending Submittal of Requested Documents / Pending Building Approval / Requires Resubmittal / Approved Pending Agency Clearances → In Review.

## Field assessment

### STATUS_NORMALIZED — 164 missing; 0 incorrect among present

Upstream mapping from CaseStatus already matches wherever both are set (crosstab is one-to-one for mapped labels). Gaps are pre-issuance / intake statuses that were never normalized:

| CaseStatus | Expected | n | Flag |
| --- | --- | --- | --- |
| Pending Submittal of Requested Documents | In Review | 81 | FILLED |
| In Screening | In Review | 32 | FILLED |
| Requires Resubmittal | In Review | 26 | FILLED |
| Pending Building Approval | In Review | 20 | FILLED |
| Approved Pending Agency Clearances | In Review | 5 | FILLED |

After repair: Final 873; Inactive 553; In Review 343; Active 231; missing 0.

### FILE_DATE — complete and correct

- Ideal: application / submittal date for all records.
- 2,000 / 2,000 populated; all match `entity.ApplyDate` calendar day (UTC).
- No FILLED / FIXED.

### PERMIT_DATE — correct when present; 2 Active/Final gaps unfillable

- Ideal: populated for Active and Final.
- Where both `PERMIT_DATE` and `IssueDate` exist, calendar day always matches (0 mismatches). Coverage pre-repair: Active 231/231; Final 871/873.
- The 2 Final gaps (`CO-2023-0004` Certificate of Occupancy; `ENCR-2023-0118` Encroachment) have `IssueDate=null`, `Issued=False`, and no alternate issuance field — left missing (same pattern as Carson Complete applications without issuance).
- Two In Review rows retain an `IssueDate`-backed `PERMIT_DATE` (revision / re-check after prior issuance); Accela/EnerGov CaseStatus remains authoritative, so status is not remapped to Active solely from IssueDate.
- No FILLED / FIXED on this sample.

After repair: Active 231/231 (100%); Final 871/873 (99.8%).

### FINAL_DATE — correct for Final; 229 spurious on non-Final

- Ideal: populated for Final.
- All 873 CaseStatus=Complete rows already have `FINAL_DATE` matching `entity.FinalDate` (0 missing, 0 mismatches).
- **FIXED 229** non-Final rows with spurious `FINAL_DATE` copied from `entity.FinalDate`:

| Pre-repair status | CaseStatus | n |
| --- | --- | --- |
| Inactive | Void | 167 |
| Inactive | Withdrawn | 49 |
| Active | Issued | 8 |
| Inactive | Plan Approval Expired | 5 |

  On Void/Withdrawn, `FinalDate` behaves as a close/void stamp (ClosedDate is unused; Issued is usually False). On Issued, CaseStatus is still open despite a FinalizeDate stamp — status is not remapped to Final from FinalDate alone.

After repair: Final 873/873 (100%); Active / In Review / Inactive have none.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 164 | 0 | 164 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 626 → 626 |
| `FINAL_DATE` | 0 | 229 | 898 → 1,127 |

Missing `FINAL_DATE` rises because incorrect non-Final values are cleared; all true Final rows remain populated.

## Artifacts

- Script: `agent/scripts/data_repair_ca_la_canada_flintridge.py` (`data_repair`)
- Summary CSV: `AGENT_DATA_PATH/la_canada_flintridge_repair_summary.csv`
