# Wellington (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Wellington**. DATA is a Tyler EnerGov payload (`entity` / `details` / optional review extras). Upstream STATUS often lagged behind current `CaseStatus` (e.g. STATUS_ORIGINAL still `plan check` / `permit issued/printed` while CaseStatus had advanced to Closed or Permit Issued/Printed), and two statuses were unmapped (`Notice of Commencement Hold`, `No Permit Obtained`). Repair FILLED 44 and FIXED 63 STATUS values (0 null remaining). FILE_DATE already matched `ApplyDate` on all 2,000 rows. PERMIT_DATE filled 30 missing IssueDate stamps after status correction; Active 100% / Final 99.6%. FINAL_DATE filled 39 Closed/CO shells and cleared 9 spurious Void/Expired stamps; Final FINAL_DATE 100%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Wellington, FL** → `agent/scripts/fl/data_repair_fl_wellington.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All 2,000 rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 163 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Content suffixes split by which canonical dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,382 | IssueDate + FinalDate/FinalizeDate |
| `energov_issued` | 288 | IssueDate, no final stamp |
| `energov_applied` | 156 | ApplyDate only |
| `energov_full_applied` | 81 | full keyset, apply only |
| `energov_full_issued` | 71 | full keyset, issued |
| `energov_full_issued_finaled` | 11 | full keyset, issued + finaled |
| `energov_finaled` | 11 | final stamp, no IssueDate |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`; strip trailing whitespace) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active / Final / Inactive |
| FINAL_DATE | `entity.FinalDate` → `details.FinalizeDate` → latest passed final-ish `processing_status` inspection; Final only |

Status bases → normalized: Closed / Certificate of Occupancy Issued → Final; Permit Issued/Printed / Notice of Commencement Hold → Active; Plan Check → In Review; Expired / Void / Abandoned / No Permit Obtained → Inactive.

## Field assessments

### STATUS_NORMALIZED

| CaseStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 1,341 | Final 1,305 / Active 24 / In Review 7 / Inactive 1 / null 4 | Lagged STATUS_ORIGINAL |
| Permit Issued/Printed | 182 | Active 157 / In Review 19 / Inactive 2 / null 4 | Lagged STATUS_ORIGINAL |
| Plan Check | 179 | In Review 179 | Correct (trailing space stripped) |
| Expired | 146 | Inactive 143 / Active 3 | 3 lagged as Active |
| Void | 74 | Inactive 74 | Correct |
| Certificate of Occupancy Issued | 35 | Final 32 / Active 3 | 3 lagged as Active |
| Notice of Commencement Hold | 27 | null 23 / In Review 4 | Unmapped upstream |
| No Permit Obtained | 13 | null 13 | Unmapped upstream |
| Abandoned | 3 | Inactive 3 | Correct |

**Root causes:**
- **STATUS_ORIGINAL lag:** Upstream normalized from a stale snapshot (`plan check`, `permit issued/printed`, `notice of commencement hold`, `expired`) while `entity.CaseStatus` had already advanced (especially Closed with FinalDate present, and Permit Issued/Printed with IssueDate).
- **Unmapped statuses:** `Notice of Commencement Hold` (post-issuance administrative hold → Active, consistent with other FL NOC-hold mappings) and `No Permit Obtained` → Inactive were absent from the upstream normalizer.
- **Trailing whitespace:** `Void `, `Abandoned `, `No Permit Obtained `, `Plan Check ` required stripping before map lookup.

**Repair performance:** FILLED 44, FIXED 63; missing 44 → 0. After: Final 1,376; Inactive 236; Active 209; In Review 179.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. All 2,000 rows equal `entity.ApplyDate` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- Coverage after repair: **100%** across all statuses. FILE > PERMIT inversions: 0.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Existing values matched `IssueDate` whenever both present (**0 calendar mismatches**).
- **30 FILLED** on shells whose upstream status still said In Review (7 Closed + 19 Permit Issued/Printed + 4 Notice of Commencement Hold) while IssueDate was already set — filled after status correction to Active/Final.
- **6 Final Closed** remain without PERMIT_DATE: `Issued=False` and blank IssueDate — no alternate issuance stamp in DATA.

Coverage after repair: Active 209/209 (100%); Final 1,370/1,376 (99.6%); In Review 0/179; Inactive 173/236 (73.3%, mostly Expired plus Void/Abandoned with prior issuance).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All already-Final Closed / CO Issued rows matched `FinalDate` / `FinalizeDate` (**0 mismatches** among already-correct Finals).
- **39 FILLED** on Closed / Certificate of Occupancy Issued shells whose upstream status lagged as Active / In Review / Inactive / null.
- **9 FIXED clears:** 8 Void + 1 Expired Inactive shells that carried FinalDate without being Closed/CO Issued.
- Non-Final correctly have no FINAL_DATE after repair.

Coverage after repair: Final 1,376/1,376 (100%); Active / In Review / Inactive 0%. Date-order inversions: FILE>PERMIT 0, PERMIT>FINAL 0, FILE>FINAL 0.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 44 | 63 | 44 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 30 | 0 | 278 → 248 |
| FINAL_DATE | 39 | 9 | 654 → 624 |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_wellington.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_wellington_repaired.parquet`
