# St. Lucie County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **St. Lucie County**. DATA is a Tyler EnerGov payload (`entity` / `details` / optional review extras). Upstream status was correct for nearly all rows; three unmapped CaseStatus values left STATUS null (FILLED), and one shell lagged with `CaseStatus=Issued` while `PermitStatus=Completed\Finaled` and FinalizeDate were set → FIXED to Final and FINAL_DATE FILLED. FILE_DATE already matched `ApplyDate` on all 1,999 rows. PERMIT_DATE filled 1 missing Issued stamp and cleared 10 spurious In Review issuance stamps. FINAL_DATE cleared 16 Active + 1 Notified shells carrying FinalDate without being Complete. After repair: STATUS 100%; FILE_DATE 100%; Active PERMIT_DATE 99.7%; Final PERMIT_DATE 97.8%; Final FINAL_DATE 100%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **St. Lucie County, FL** → `agent/scripts/fl/data_repair_fl_st_lucie_county.py` (1,999 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All 1,999 rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 395 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Content suffixes split by which canonical dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 569 | IssueDate + FinalDate/FinalizeDate |
| `energov_issued` | 533 | IssueDate, no final stamp |
| `energov_applied` | 499 | ApplyDate only |
| `energov_full_applied` | 240 | full keyset, apply only |
| `energov_full_issued` | 116 | full keyset, issued |
| `energov_full_issued_finaled` | 29 | full keyset, issued + finaled |
| `energov_full_finaled` | 10 | full keyset, finaled only |
| `energov_finaled` | 3 | final stamp, no IssueDate |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`); upgrade Issued→Final when PermitStatus maps to Final and a final date exists |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active / Final / Inactive |
| FINAL_DATE | `entity.FinalDate` → `details.FinalizeDate` → latest passed final-ish `processing_status` inspection; Final only |

Status bases → normalized: `Completed\Finaled` / Admin Closeout → Final; Issued → Active; In Review / Notified / Fees Due / Fees Paid / Submitted / Submitted - Online / On Hold / On Hold (See Conditions) → In Review; Expired / Void / Denied / Withdrawn → Inactive.

## Field assessments

### STATUS_NORMALIZED

| CaseStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Issued | 610 | Active 609 / **Active→Final 1** | One entity lag |
| Completed\Finaled | 556 | Final | Correct |
| In Review | 412 | In Review | Correct |
| Submitted - Online | 103 | In Review | Correct |
| Notified | 87 | In Review | Correct |
| Expired | 75 | Inactive | Correct |
| Denied | 56 | Inactive | Correct |
| Void | 46 | Inactive | Correct |
| Withdrawn | 19 | Inactive | Correct (trailing space stripped) |
| Fees Paid | 13 | In Review | Correct |
| On Hold | 10 | In Review | Correct |
| Fees Due | 6 | In Review | Correct |
| Submitted | 3 | In Review | Correct |
| On Hold (See Conditions) | 2 | **null → In Review** | Unmapped upstream |
| Admin Closeout | 1 | **null → Final** | Unmapped; FinalizeDate present |

**Root causes:**
- **1 FIXED:** `ELER-2506-006253` had `CaseStatus=Issued` / `STATUS_ORIGINAL=issued` while `PermitStatus=Completed\Finaled`, `FinalizeDate=2025-06-27`, and a passed Final Electrical Residential inspection. Entity lagged details.
- **3 FILLED:** `On Hold (See Conditions)` (2) and `Admin Closeout` (1) were absent from the upstream normalizer.

**Repair performance:** FILLED 3, FIXED 1; missing 3 → 0. After: In Review 636; Active 609; Final 558; Inactive 196.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. All 1,999 rows equal `entity.ApplyDate` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- Coverage after repair: **100%** across all statuses. FILE > PERMIT inversions: 0.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Existing values matched `IssueDate` whenever both present (**0 calendar mismatches**).
- **1 FILLED** on Issued `ROOFR-2404-005134` (`IssueDate=2026-05-24`, previously null — likely excluded as “future” at an earlier scrape).
- **10 FIXED clears** on In Review / Notified / Fees Due rows that still carried `IssueDate` (`Issued=True` but CaseStatus remained pre-issuance).
- **14 Active/Final** remain without PERMIT_DATE: 2 Issued + 11 Completed\Finaled + 1 Admin Closeout with `Issued=False` and blank IssueDate — no alternate issuance stamp in DATA.

Coverage after repair: Active 607/609 (99.7%); Final 546/558 (97.8%); In Review 0/636; Inactive 84/196 (42.9%, mostly Expired plus a few Void/Withdrawn with prior issuance).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All already-Final `Completed\Finaled` rows matched `FinalDate` / `FinalizeDate` (**0 mismatches**).
- **1 FILLED** on the Issued→Final upgrade from `FinalizeDate`.
- **17 FIXED clears:** 16 Active Issued shells and 1 Notified shell that carried `FinalDate`/`FinalizeDate` without `PermitStatus=Completed\Finaled` (common on driveway / vegetation / zoning shells where EnerGov stamps FinalDate near IssueDate).
- Admin Closeout already had matching FINAL_DATE; left intact after status fill.
- Non-Final correctly have no FINAL_DATE after repair.

Coverage after repair: Final 558/558 (100%); Active / In Review / Inactive 0%. Residual agency quirk: 1 PERMIT > FINAL inversion (`TEMP-2309-000023`, IssueDate one day after FinalDate) — left as-is (stamps match DATA).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 1 | 3 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1 | 10 | 753 → 762 |
| FINAL_DATE | 1 | 17 | 1,425 → 1,441 |

Remaining structural gaps: 14 Active/Final shells without IssueDate (PERMIT_DATE); 1 agency FinalDate-before-IssueDate order quirk.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_st_lucie_county.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_st_lucie_county_repaired.parquet`
