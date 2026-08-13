# Maitland (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Maitland**. DATA is a Tyler EnerGov payload (`entity` / `details` / optional review extras). Upstream STATUS often lagged behind current `CaseStatus` (e.g. STATUS_ORIGINAL still `issued` / `in review` while CaseStatus had advanced to Complete or Issued), and several review/expired statuses were unmapped. Repair FILLED 36 and FIXED 27 STATUS values (0 null remaining). FILE_DATE already matched `ApplyDate` on all 2,000 rows. PERMIT_DATE filled 10 missing IssueDate stamps after status correction to Active/Final and cleared 34 spurious In Review issuance stamps; Active 100% / Final 99.9%. FINAL_DATE filled 14 Complete shells and cleared 90 spurious non-Final stamps; Final FINAL_DATE 100%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Maitland, FL** → `agent/scripts/fl/data_repair_fl_maitland.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All 2,000 rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 80 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Content suffixes split by which canonical dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,604 | IssueDate + FinalDate/FinalizeDate |
| `energov_applied` | 172 | ApplyDate only |
| `energov_issued` | 141 | IssueDate, no final stamp |
| `energov_full_applied` | 57 | full keyset, apply only |
| `energov_full_issued` | 22 | full keyset, issued |
| `energov_finaled` | 3 | final stamp, no IssueDate |
| `energov_full_issued_finaled` | 1 | full keyset, issued + finaled |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active / Final / Inactive |
| FINAL_DATE | `entity.FinalDate` → `details.FinalizeDate` → latest passed final-ish `processing_status` inspection; Final only |

Status bases → normalized: Complete → Final; Issued → Active; Fees Due / Fees Paid / On Hold / In Review (+ Requires Resubmittal) / Sufficiency Check (+ Requires Resubmittal) / Submitted - Online / Permit Processing Fee Due → In Review; Expired / Expired (Not Issued) / Void → Inactive.

## Field assessments

### STATUS_NORMALIZED

| CaseStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Complete | 1,508 | Final 1,494 / Active 11 / Inactive 2 / In Review 1 | Lagged STATUS_ORIGINAL |
| Void | 161 | Inactive 161 | Correct |
| Expired | 92 | Inactive 89 / Active 3 | 3 lagged as Active |
| Issued | 73 | Active 62 / In Review 9 / null 2 | Lagged / unmapped |
| Fees Due | 62 | In Review 61 / Active 1 | 1 lagged as Active |
| On Hold | 36 | In Review 36 | Correct |
| In Review | 24 | In Review 24 | Correct |
| In Review - Requires Resubmittal | 18 | null 16 / In Review 2 | Mostly unmapped |
| Sufficiency Check | 10 | null 10 | Unmapped |
| Submitted - Online | 7 | In Review 7 | Correct |
| Permit Processing Fee Due | 3 | null 3 | Unmapped |
| Expired (Not Issued) | 3 | null 3 | Unmapped |
| Sufficiency Check - Requires Resubmittal | 2 | null 2 | Unmapped |
| Fees Paid | 1 | In Review 1 | Correct |

**Root causes:**
- **STATUS_ORIGINAL lag:** Upstream normalized from a stale snapshot (`issued`, `in review`, `fees due`, `on hold`, `expired`) while `entity.CaseStatus` had already advanced (especially Complete with FinalDate present, and Issued with IssueDate).
- **Unmapped statuses:** `In Review - Requires Resubmittal`, `Sufficiency Check`, `Sufficiency Check - Requires Resubmittal`, `Permit Processing Fee Due`, and `Expired (Not Issued)` were absent from the upstream normalizer → null STATUS_NORMALIZED.

**Repair performance:** FILLED 36, FIXED 27; missing 36 → 0. After: Final 1,508; Inactive 256; In Review 163; Active 73.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. All 2,000 rows equal `entity.ApplyDate` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- Coverage after repair: **100%** across all statuses.
- 8 rows have entity vs details ApplyDate differing by timezone offset only; upstream (and repair) correctly use the entity calendar day.
- 9 rows have agency ApplyDate after IssueDate (source-data anomalies, left as-is). FILE > PERMIT inversions: 9.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Existing values matched `IssueDate` whenever both present (**0 calendar mismatches** among kept values).
- **10 FILLED** on Issued / Complete shells whose upstream status still said In Review / null while IssueDate was already set — filled after status correction to Active/Final.
- **34 FIXED clears:** In Review rows (mostly Fees Due, plus one Requires Resubmittal) that carried leftover IssueDate stamps inconsistent with In Review.
- **1 Final Complete** remains without PERMIT_DATE: `DEMO-6-16-27874` has `Issued=False` and blank IssueDate — no alternate issuance stamp in DATA.

Coverage after repair: Active 73/73 (100%); Final 1,507/1,508 (99.9%); In Review 0/163; Inactive 154/256 (60.2%, mostly Expired plus Void with prior issuance).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All already-Final Complete rows matched `FinalDate` / `FinalizeDate` (**0 mismatches** among already-correct Finals).
- **14 FILLED** on Complete shells whose upstream status lagged as Active (11) / Inactive (2) / In Review (1).
- **90 FIXED clears:** 57 Void + 29 Fees Due + 4 Issued shells that carried FinalDate without being Complete.
- Non-Final correctly have no FINAL_DATE after repair. Every Complete row has FinalDate in DATA → Final FINAL_DATE 100% without needing inspection fallback.

Coverage after repair: Final 1,508/1,508 (100%); Active / In Review / Inactive 0%. PERMIT>FINAL inversions: 1 (agency IssueDate after FinalDate on `COMM-9-11-18409`).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 36 | 27 | 36 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 10 | 34 | 242 → 266 |
| FINAL_DATE | 14 | 90 | 416 → 492 |

Missing PERMIT_DATE / FINAL_DATE counts rise because spurious In Review / Void / Issued stamps are cleared; Active/Final coverage improves.

Remaining structural gaps: 1 Complete Final without IssueDate; agency date-order anomalies (Apply after Issue, Issue after Final) preserved from source.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_maitland.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_maitland_repaired.parquet`
