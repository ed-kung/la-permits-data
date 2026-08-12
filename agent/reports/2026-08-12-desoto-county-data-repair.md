# DeSoto County (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, DeSoto County was first. Its DATA is a Tyler EnerGov payload (`entity` / `details` / optional `reviews` extras). STATUS_NORMALIZED was null on 7 rows and wrong on 12 more because it followed a stale `STATUS_ORIGINAL` while `entity.CaseStatus` already said Complete / Expired / Issued — all 19 were FILLED or FIXED. FILE_DATE already matched `ApplyDate` on every row. PERMIT_DATE gained 3 FILLED values after Issued/Complete status corrections. FINAL_DATE gained 8 FILLED values on Complete→Final upgrades, FIXED 1 stale final stamp, and cleared 8 spurious non-Final finals. Post-repair, every row matches EnerGov CaseStatus/date sources with no residual mismatches; Active/Final have full PERMIT_DATE and Final has full FINAL_DATE.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **DeSoto County, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_desoto_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_desoto_county_repaired.parquet`

## DATA schema

All rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 52 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Variants are classified by which canonical dates are populated:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,481 | Issued + Finaled |
| `energov_issued` | 427 | Issued, no Finaled |
| `energov_applied` | 40 | Apply only |
| `energov_full_issued` | 28 | full keyset, issued |
| `energov_full_applied` | 14 | full keyset, apply only |
| `energov_full_issued_finaled` | 10 | full keyset, issued + finaled |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active/Final/Inactive |
| FINAL_DATE | `entity.FinalDate` (fallback `details.FinalizeDate`) for Final only |

CaseStatus → normalized: Complete → Final; Issued → Active; In Review / Submitted / On Hold / Ready to Issue* / Requires Resubmittal / Stop Work Order → In Review; Expired / Void / Denied → Inactive.

## Field assessments

### STATUS_NORMALIZED

**7 missing** (`Ready to Issue - PENDING` ×2, `Requires Resubmittal` ×3, `Ready to Issue - Owner Builder` ×1 with no IssueDate, plus 1 `Issued` shell whose STATUS_ORIGINAL was still `ready to issue - owner builder`).

**12 incorrect** from stale STATUS_ORIGINAL vs current CaseStatus:

- Complete still labeled Active (7) or In Review (2) — STATUS_ORIGINAL was `issued` / `ready to issue` / `fees due`
- Expired still labeled Active (2) — STATUS_ORIGINAL was `issued`
- Issued still labeled In Review (1) — STATUS_ORIGINAL was `in review`

**7 FILLED / 12 FIXED.** Distribution: Final 1,474→1,483; Inactive 365→367; Active 134→127; In Review 20→23; null 7→0.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. When both present (2,000 rows), FILE_DATE always equals `ApplyDate` (**0 FILLED / 0 FIXED**).
- Coverage after repair: 100% across all statuses.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When both present, PERMIT_DATE always equals `IssueDate` (**0 FIXED**).
- **3 FILLED**: Complete/Issued rows that had IssueDate but blank PERMIT_DATE under an In Review / null label.
- Remaining gap: **54** = 23 In Review (pre-issuance, no IssueDate expected) + 31 Inactive never-issued Denied/Void shells. Active/Final gap: **0**.

Coverage after repair: Active 127/127 (100%); Final 1,483/1,483 (100%); In Review 0/23; Inactive 336/367 (91.6%, issued-then-expired/voided/denied).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- **8 FILLED** on Complete→Final upgrades that already had `FinalDate` / `FinalizeDate` but blank FINAL_DATE under the old Active/In Review label.
- **1 FIXED** value: Active Complete row whose FINAL_DATE (2024-06-03) lagged `FinalDate` (2024-08-19).
- **8 FIXED clears**: non-Final Denied/Void/Issued rows incorrectly carrying FinalDate closeout stamps (plus the upgraded row counted above as a value fix, not a clear).
- Remaining Final gap: **0**. Every Complete row carries FinalDate.

Coverage after repair: Final 1,483/1,483 (100%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 7 | 12 | 7 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 3 | 0 | 57 → 54 |
| FINAL_DATE | 8 | 9 | 517 → 517 |

FINAL_DATE missing count is unchanged because 8 fills on upgraded Final rows were offset by 8 clears on non-Final rows; the Final subset went from 1,474/1,474 with dates (under the old label) to 1,483/1,483 after upgrades.

Date-order quirks left as agency-sourced (not inventable): FILE_DATE > PERMIT_DATE on 8 rows; PERMIT_DATE > FINAL_DATE on 5 rows.
