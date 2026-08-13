# North Lauderdale (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **North Lauderdale**. DATA is a Tyler EnerGov payload (`entity` / `details` / optional review extras). Upstream status was already correct for nearly all rows; one shell lagged with `CaseStatus=Issued` while `PermitStatus=Complete` and `FinalizeDate` were set → FIXED to Final and FINAL_DATE FILLED. FILE_DATE already matched `ApplyDate` on all 2,000 rows. PERMIT_DATE cleared 2 spurious In Review issuance stamps; 2 Complete shells remain without IssueDate. FINAL_DATE cleared 4 In Review 40-year inspection shells carrying FinalDate. After repair: STATUS 100%; FILE_DATE 100%; Active PERMIT_DATE 100%; Final PERMIT_DATE 99.9%; Final FINAL_DATE 100%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **North Lauderdale, FL** → `agent/scripts/fl/data_repair_fl_north_lauderdale.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All 2,000 rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 43 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Content suffixes split by which canonical dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,606 | IssueDate + FinalDate/FinalizeDate |
| `energov_applied` | 170 | ApplyDate only |
| `energov_issued` | 167 | IssueDate, no final stamp |
| `energov_full_applied` | 36 | full keyset, apply only |
| `energov_finaled` | 14 | final stamp, no IssueDate |
| `energov_full_finaled` | 4 | full keyset, finaled only |
| `energov_full_issued` | 3 | full keyset, issued |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`); upgrade Issued→Final when PermitStatus=Complete and a final date exists |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active / Final / Inactive |
| FINAL_DATE | `entity.FinalDate` → `details.FinalizeDate` → latest passed final-ish `processing_status` inspection; Final only |

StatusValue bases → normalized: Complete→Final; Issued→Active; In Review / Fees Due / Fees Paid / Submitted / Submitted - Online / On Hold→In Review; Expired / Void / Withdrawn→Inactive.

## Field assessments

### STATUS_NORMALIZED

| CaseStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Complete | 1,606 | Final | Correct |
| Expired | 197 | Inactive | Correct |
| In Review | 97 | In Review | Correct |
| Issued | 43 | Active 42 / **Active→Final 1** | One entity lag |
| Fees Due | 22 | In Review | Correct |
| Submitted - Online | 15 | In Review | Correct |
| Fees Paid | 13 | In Review | Correct |
| Void | 3 | Inactive | Correct |
| On Hold | 2 | In Review | Correct |
| Submitted | 1 | In Review | Correct |
| Withdrawn | 1 | Inactive | Correct |

**Root cause (1 FIXED):** `BLDG-02091-2024` had `CaseStatus=Issued` / `STATUS_ORIGINAL=issued` while `PermitStatus=Complete`, `FinalizeDate=2024-08-27`, and passed final Door/Windows inspections. Entity lagged details.

**Repair performance:** FILLED 0, FIXED 1; missing 0 → 0. After: Final 1,607; Inactive 201; In Review 150; Active 42.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. All 2,000 rows equal `entity.ApplyDate` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- One row has `details.ApplyDate` one calendar day later than entity (UTC offset); entity is preferred and already matches upstream.
- Coverage after repair: **100%** across all statuses. FILE > PERMIT inversions: 0.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Existing values matched `IssueDate` whenever both present (**0 calendar mismatches**).
- **2 FIXED clears** on In Review rows that still carried `IssueDate` (`Issued=True` but CaseStatus remained In Review — 2006-era shells).
- **2 Final** (`Complete`, `Issued=False`) have blank IssueDate → PERMIT_DATE stays missing; no alternate issuance stamp in DATA (`CompleteDate` / `ClosedDate` always null).

Coverage after repair: Active 42/42 (100%); Final 1,605/1,607 (99.9%); In Review 0/150; Inactive 127/201 (63.2%, issued-then-expired/withdrawn).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All already-Final Complete rows matched `FinalDate` / `FinalizeDate` (**0 mismatches** among those pairs).
- **1 FILLED** on the Issued→Final upgrade from `FinalizeDate`.
- **4 FIXED clears** on In Review `40 Year Building Inspection` shells that carried `FinalDate` minutes after ApplyDate without being Complete.
- Non-Final correctly have no FINAL_DATE after repair.

Coverage after repair: Final 1,607/1,607 (100%); Active / In Review / Inactive 0%. Residual agency quirks: 3 PERMIT > FINAL and 1 FILE > FINAL inversions where EnerGov `FinalDate` precedes `IssueDate`/`ApplyDate` — left as-is (stamps match DATA).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 2 | 224 → 226 |
| FINAL_DATE | 1 | 4 | 390 → 393 |

Remaining structural gaps: 2 Complete shells without IssueDate (Final PERMIT_DATE); 3 agency FinalDate-before-IssueDate order quirks.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_north_lauderdale.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_north_lauderdale_repaired.parquet`
