# Palm Beach Gardens (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Palm Beach Gardens**. DATA is a Tyler EnerGov payload (`entity` / `details` / optional review extras). Upstream STATUS left 178 rows null for city-specific CaseStatus values (Void -*, Verify Application*, Pending Issuance/Closure*). Repair FILLED all 178 STATUS values (0 FIXED; 0 null remaining). FILE_DATE already matched `ApplyDate` on all 2,000 rows. PERMIT_DATE needed no fill/fix against IssueDate; Active 100% / Final 94.6% (36 Complete revisions never issued). FINAL_DATE cleared 95 spurious non-Final stamps (Void closures + one In Review); Final FINAL_DATE 100%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Palm Beach Gardens, FL** → `agent/scripts/fl/data_repair_fl_palm_beach_gardens.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All 2,000 rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 426 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). `processing_status` is empty on every sample row. Content suffixes split by which canonical dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued` | 707 | IssueDate, no final stamp |
| `energov_issued_finaled` | 623 | IssueDate + FinalDate/FinalizeDate |
| `energov_full_issued` | 293 | full keyset, issued |
| `energov_applied` | 157 | ApplyDate only |
| `energov_finaled` | 87 | final stamp, no IssueDate |
| `energov_full_applied` | 76 | full keyset, apply only |
| `energov_full_finaled` | 32 | full keyset, final only |
| `energov_full_issued_finaled` | 25 | full keyset, issued + finaled |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`; strip whitespace) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active / Final / Inactive |
| FINAL_DATE | `entity.FinalDate` → `details.FinalizeDate` → latest passed final-ish `processing_status` inspection; Final only |

Status bases → normalized: Complete → Final; Issued / Inspections / Approved / Pending Closure → Active; Pending Closure - On Hold → Active if IssueDate else In Review; In Review / Submitted - Online / Verify Application (+ On Hold) / Pending Issuance - On Hold → In Review; Expired / Void* → Inactive.

## Field assessments

### STATUS_NORMALIZED

| CaseStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Complete | 672 | Final 672 | Correct |
| Issued | 619 | Active 619 | Correct |
| Inspections | 340 | Active 340 | Correct |
| In Review | 138 | In Review 138 | Correct |
| Verify Application - On Hold | 56 | null 56 | Unmapped → In Review |
| Void - Incorrect Permit Type | 48 | null 48 | Unmapped → Inactive |
| Expired | 37 | Inactive 37 | Correct |
| Pending Issuance - On Hold | 20 | null 20 | Unmapped → In Review |
| Void - Permit Submitted in Error | 20 | null 20 | Unmapped → Inactive |
| Submitted - Online | 12 | In Review 12 | Correct |
| Void - Cancelled by Contact | 11 | null 11 | Unmapped → Inactive |
| Void - Master Permit in Legacy System | 9 | null 9 | Unmapped → Inactive |
| Void - Administratively Closed | 6 | null 6 | Unmapped → Inactive (trailing space in CaseStatus) |
| Approved | 4 | Active 4 | Correct |
| Pending Closure - On Hold | 4 | null 4 | Unmapped → Active (1 issued) / In Review (3) |
| Pending Closure | 3 | null 3 | Unmapped → Active |
| Verify Application | 1 | null 1 | Unmapped → In Review |

**Root cause:** Upstream normalizer covered common EnerGov statuses (Complete / Issued / Inspections / In Review / Expired / Submitted - Online / Approved) but omitted Palm Beach Gardens–specific Void reasons, verify-application holds, and pending-issuance/closure states → 178 null `STATUS_NORMALIZED`.

**Repair performance:** FILLED 178, FIXED 0; missing 178 → 0. After: Active 967; Final 672; In Review 230; Inactive 131.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. All 2,000 rows equal `entity.ApplyDate` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- Coverage after repair: **100%** across all statuses.
- No FILE > PERMIT inversions.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Existing values matched `IssueDate` whenever both present (**0 calendar mismatches**; **0 FILLED / 0 FIXED**).
- Missing PERMIT_DATE (352) coincides exactly with blank IssueDate — mostly In Review / Void-never-issued shells plus 36 Complete revisions.
- **36 Final Complete** remain without PERMIT_DATE: mostly `Revisions - Residential/Commercial` (plus two Fire plan types) with `Issued=False` and blank IssueDate — no alternate issuance stamp in DATA (`processing_status` empty).

Coverage after repair: Active 967/967 (100%); Final 636/672 (94.6%); In Review 0/230; Inactive 45/131 (34.4%, Void/Expired that had been issued).

### FINAL_DATE

Ideal: populated for Final.

- All 672 Complete/Final rows already matched `entity.FinalDate` (**0 FILLED** among Final).
- **95 FIXED clears:** 94 Void* shells and 1 In Review row carried FinalDate/FinalizeDate (agency close/void stamp) while not being Final — cleared after STATUS fill / for consistency with Final-only FINAL_DATE rule.
- Final coverage after repair: **672/672 (100%)**. Active / In Review / Inactive: 0%.

## Repair script

`agent/scripts/fl/data_repair_fl_palm_beach_gardens.py` — `data_repair(df)` overwrites incorrect fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

## Artifacts

- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_palm_beach_gardens_repaired.parquet`
