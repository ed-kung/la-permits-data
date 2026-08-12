# Hallandale Beach (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Hallandale Beach was first. Its DATA is a Tyler EnerGov payload (`entity` / `details` / optional `reviews` extras). STATUS_NORMALIZED was null on **128** `Required` rows (never mapped from `STATUS_ORIGINAL`) — all FILLED as In Review. FILE_DATE and PERMIT_DATE already matched `ApplyDate` / `IssueDate` whenever present (**0** value changes). FINAL_DATE cleared **49** spurious non-Final stamps (Inactive VOID/Expired, one Active with FinalDate before IssueDate, one Required). After repair: status complete; Final FINAL_DATE **99.9%**; Active/Final PERMIT_DATE **97.3% / 96.6%**. Remaining gaps are blank EnerGov issuance/final stamps with no alternate dates in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Hallandale Beach, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_hallandale_beach.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_hallandale_beach_repaired.parquet`

## DATA schema

All rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 24 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Variants are classified by which canonical dates are populated:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,581 | Issued + Finaled |
| `energov_issued` | 190 | Issued, no Finaled |
| `energov_applied` | 129 | Apply only (mostly Required) |
| `energov_finaled` | 76 | Finaled, no IssueDate |
| `energov_full_applied` | 17 | full keyset, apply only |
| `energov_full_issued` | 4 | full keyset, issued |
| `energov_full_finaled` | 3 | full keyset, finaled only |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active/Final/Inactive |
| FINAL_DATE | `entity.FinalDate` (fallback `details.FinalizeDate`) for Final only |

CaseStatus → normalized: Finaled / CO Issued / CC Issued / Closed → Final; Active → Active; Submitted / In-Review / Required → In Review; Cancelled / Expired / REVOKED / Rejected / VOID → Inactive. `CaseStatus` and `details.PermitStatus` always agree in this sample.

## Field assessments

### STATUS_NORMALIZED

Upstream distribution: Final 1,612 · Inactive 192 · Active 58 · In Review 10 · **null 128**.

The 128 nulls are all `CaseStatus = Required` / `STATUS_ORIGINAL = required` with `Issued=False` and blank `IssueDate` (pre-issuance shells, often with holds or unpaid-fee flags unset) → **FILLED In Review**.

No incorrect non-null statuses relative to CaseStatus (**0 FIXED**). After: Final 1,612 · Inactive 192 · In Review 138 · Active 58 · null **0**.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. When both present (2,000 rows), FILE_DATE always equals `ApplyDate` (**0 FILLED / 0 FIXED**).
- Coverage after repair: **100%** across all statuses.
- One agency quirk remains: ApplyDate one calendar day after IssueDate on Finaled `PSUB-16-01670` (FILE_DATE > PERMIT_DATE). Left as-is.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When IssueDate and PERMIT_DATE were both present, they always matched (**0 FILLED / 0 FIXED**). Missing PERMIT_DATE always mirrored blank IssueDate.
- Active/Final still missing PERMIT_DATE: **45** = Finaled (42) + Closed (1) with null IssueDate, plus 2 zoning `Active` shells (`PZ-*`) with `Issued=False` / null IssueDate. Not inventable from DATA (`CompleteDate` / `ClosedDate` always null; fee paid dates are not reliable issuance proxies).
- In Review correctly has **0** PERMIT_DATE after repair.

Coverage after repair: Active 56/58 (96.6%); Final 1,569/1,612 (97.3%); In Review 0/138; Inactive 150/192 (78.1%, issued-then-voided/expired/cancelled).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Existing FINAL_DATE values that matched `FinalDate` were already correct on Final rows (**0 FILLED**).
- **49 FIXED clears** of non-Final FINAL_DATE:
  - Inactive VOID (44) / Expired (3) carrying FinalDate
  - Active with FinalDate **before** IssueDate (1; `PGAS-24-00315`)
  - Required → In Review carrying FinalDate (1)
- Remaining Final gap: **1** Finaled shell (`SP-PCND-17-01210`) with null `FinalDate` / `FinalizeDate`. No alternate final date in DATA.
- PERMIT_DATE > FINAL_DATE inversions after repair: **0** (the Active case was cleared).

Coverage after repair: Final 1,611/1,612 (99.9%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 128 | 0 | 128 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 225 → 225 |
| FINAL_DATE | 0 | 49 | 340 → 389 |

Residual mismatches vs EnerGov CaseStatus / ApplyDate / IssueDate / FinalDate: **0**. Date-order checks after repair: FILE_DATE > PERMIT_DATE inversions **1** (unrepairable agency quirk); PERMIT_DATE > FINAL_DATE inversions **0**.
