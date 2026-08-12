# Deltona (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Deltona was first. Its DATA is a Tyler EnerGov payload (`entity` / `details` / optional `reviews` extras). STATUS_NORMALIZED was null on 76 rows (unmapped `SUBMITTED ON-LINE` / `UNDER E-REVIEW` / `ENGINEERING REVIEW`) and wrong on 189 more (APPROVED animal-tag shells labeled Active without issuance; ISSUED / APPROVED rows that already carried `FinalDate` still labeled Active) — all 265 were FILLED or FIXED. FILE_DATE already matched `ApplyDate` on every row. PERMIT_DATE needed no value changes (all existing stamps already equaled `IssueDate`). FINAL_DATE cleared 5 spurious Inactive finals (EXPIRED / CANCELLED). Post-repair, every row matches EnerGov status/date sources with no residual mismatches; remaining Final FINAL_DATE gaps are three FINALED shells with null `FinalDate`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Deltona, FL** (1,999 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_deltona.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_deltona_repaired.parquet`

## DATA schema

All rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 146 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Variants are classified by which canonical dates are populated:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 871 | Issued + Finaled |
| `energov_issued` | 684 | Issued, no Finaled |
| `energov_applied` | 290 | Apply only |
| `energov_full_issued` | 101 | full keyset, issued |
| `energov_full_applied` | 24 | full keyset, apply only |
| `energov_full_issued_finaled` | 21 | full keyset, issued + finaled |
| `energov_finaled` | 8 | Finaled, no IssueDate |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active/Final/Inactive |
| FINAL_DATE | `entity.FinalDate` (fallback `details.FinalizeDate`) for Final only |

CaseStatus → normalized: FINALED / COMPLETED → Final; ISSUED / ISSUED ONLINE → Active; APPROVED → Active only when `IssueDate` / `Issued` is set, else In Review; SUBMITTED / SUBMITTED ON-LINE / UNDER E-REVIEW / UNDER REVIEW / ENGINEERING REVIEW / READY TO ISSUE → In Review; VOID / CANCELLED / EXPIRED / DENIED → Inactive. ISSUED / ISSUED ONLINE / APPROVED rows that already carry `FinalDate` / `FinalizeDate` are upgraded to Final (agency often leaves CaseStatus at the issued/approved label after finaling).

## Field assessments

### STATUS_NORMALIZED

**76 missing.** `SUBMITTED ON-LINE` (60), `UNDER E-REVIEW` (15), and `ENGINEERING REVIEW` (1) were never mapped from `STATUS_ORIGINAL`.

**189 incorrect:**

- APPROVED animal-tag / vet-tag shells labeled Active with `Issued=False` and blank `IssueDate` (133) → FIXED to In Review
- ISSUED / ISSUED ONLINE / APPROVED rows that already carry `FinalDate` while still labeled Active (56; 52 APPROVED vet tags + 4 ISSUED / ISSUED ONLINE building permits) → FIXED to Final

**76 FILLED / 189 FIXED.** Distribution: Final 842→898; Active 843→654; In Review 37→246; Inactive 201→201; null 76→0.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. When both present (1,999 rows), FILE_DATE always equals `ApplyDate` (**0 FILLED / 0 FIXED**).
- Coverage after repair: 100% across all statuses.
- Note: 3 source rows have ApplyDate one calendar day after IssueDate (timezone edge); left as-is.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When IssueDate and PERMIT_DATE were both present, they always matched (**0 FILLED / 0 FIXED**).
- Remaining Active/Final gap: **8** = APPROVED shells upgraded to Final via `FinalDate` but with null `IssueDate` / `Issued=False` (vet animal tags). Not inventable from DATA.
- Remaining overall gap: **322** (unchanged count; composition shifted as Active→In Review moves no longer require PERMIT_DATE).

Coverage after repair: Active 654/654 (100%); Final 890/898 (99.1%); In Review 0/246; Inactive 133/201 (66.2%, issued-then-voided/canceled/expired).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Existing FINAL_DATE values that matched `FinalDate` were already correct on Final rows; Active→Final upgrades kept the stamp already present (**0 FILLED**).
- **5 FIXED clears**: Inactive EXPIRED (4) / CANCELLED (1) incorrectly carrying `FinalDate`.
- Remaining Final gap: **3** FINALED shells with null `FinalDate` / `FinalizeDate`. No alternate final date in `CompleteDate` / `ClosedDate` (both always null in this sample).

Coverage after repair: Final 895/898 (99.7%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 76 | 189 | 76 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 322 → 322 |
| FINAL_DATE | 0 | 5 | 1,099 → 1,104 |

Residual mismatches vs EnerGov sources after repair: status 0, file 0, permit 0, final 0.
