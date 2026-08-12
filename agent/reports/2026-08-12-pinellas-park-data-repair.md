# Pinellas Park (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Pinellas Park was first. Its DATA is a Tyler EnerGov payload (`entity` / `details` / optional `reviews` extras). STATUS_NORMALIZED was wrong on 17 rows because it followed a stale `STATUS_ORIGINAL` while `CaseStatus` / `PermitStatus` already said Finaled, Issued, Void, or Expired — all 17 were FIXED. FILE_DATE already matched `ApplyDate` on every row. PERMIT_DATE gained 4 FILLED values after Issued/Finaled status corrections. FINAL_DATE gained 13 FILLED values on Active/In Review→Final upgrades and cleared 125 spurious non-Final finals (mostly Expired/Abandoned/Void). Post-repair, every row matches EnerGov status/date sources with no residual mismatches; Final has full FINAL_DATE; Active/Final PERMIT_DATE gaps are only 5 never-issued shells with null `IssueDate`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Pinellas Park, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_pinellas_park.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_pinellas_park_repaired.parquet`

## DATA schema

All rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 49 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Variants are classified by which canonical dates are populated:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,679 | Issued + Finaled |
| `energov_issued` | 141 | Issued, no Finaled |
| `energov_applied` | 105 | Apply only |
| `energov_finaled` | 26 | Finaled, no IssueDate |
| `energov_full_issued` | 25 | full keyset, issued |
| `energov_full_applied` | 20 | full keyset, apply only |
| `energov_full_issued_finaled` | 4 | full keyset, issued + finaled |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`); override to Final when either status is `Finaled` |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active/Final/Inactive |
| FINAL_DATE | `entity.FinalDate` (fallback `details.FinalizeDate`) for Final only |

CaseStatus → normalized: Finaled → Final; Issued → Active; In Review / Submitted / Submitted - Online / On Hold / Fees Due / Fees Paid → In Review; Expired / Void / Abandoned → Inactive.

## Field assessments

### STATUS_NORMALIZED

**0 missing.** All 2,000 rows had a normalized status.

**17 incorrect** from stale STATUS_ORIGINAL vs current EnerGov status:

- Finaled still labeled Active (5) or In Review (1) — STATUS_ORIGINAL was `issued` / `on hold`
- CaseStatus still `Issued` while PermitStatus is `Finaled` (with `FinalizeDate` and a completed Final Building inspection) still labeled Active (6) or In Review (1) — upgraded to Final
- Issued still labeled In Review (2) — STATUS_ORIGINAL was `on hold` / `fees due`
- Void still labeled In Review (1); Expired still labeled Active (1)

**0 FILLED / 17 FIXED.** Distribution: Final 1,571→1,584; Inactive 303→305; Active 63→53; In Review 63→58.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. When both present (2,000 rows), FILE_DATE always equals `ApplyDate` (**0 FILLED / 0 FIXED**).
- Coverage after repair: 100% across all statuses.
- Note: 3 source rows have ApplyDate one calendar day after IssueDate (timezone / agency stamp quirk); left as-is.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When its IssueDate and PERMIT_DATE were both present, they always matched (**0 FIXED**).
- **4 FILLED**: Issued / Finaled rows that had IssueDate but blank PERMIT_DATE under an In Review label.
- Remaining Active/Final gap: **5** = 4 Finaled shells with `Issued=False` and null IssueDate + 1 Issued shell with null IssueDate. Not inventable from DATA.
- Remaining overall gap: **151** = those 5 + 58 In Review (pre-issuance) + 88 Inactive never-issued Void/Abandoned/Expired shells.

Coverage after repair: Active 52/53 (98.1%); Final 1,580/1,584 (99.7%); In Review 0/58; Inactive 217/305 (71.1%, issued-then-expired/voided/abandoned).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- **13 FILLED** on Active/In Review→Final upgrades that already had `FinalDate` / `FinalizeDate` but blank FINAL_DATE under the old label.
- **125 FIXED clears**: non-Final rows incorrectly carrying final/closeout stamps — Expired (90), Abandoned (19), Void (15), plus 1 Active Issued shell with a FinalDate.
- Remaining Final gap: **0**. Every Finaled / PermitStatus-Finaled row carries FinalDate or FinalizeDate.
- One legacy Finaled row has IssueDate after FinalDate in the source JSON; left as-is.

Coverage after repair: Final 1,584/1,584 (100%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 17 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 4 | 0 | 155 → 151 |
| FINAL_DATE | 13 | 125 | 304 → 416 |

Missing FINAL_DATE rises because spurious Inactive/Active finals are cleared. Residual mismatches vs EnerGov sources after repair: status 0, file 0, permit 0, final 0.
