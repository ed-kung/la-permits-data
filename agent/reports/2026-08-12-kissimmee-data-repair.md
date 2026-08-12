# Kissimmee (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Kissimmee was first. Its DATA is a Tyler EnerGov payload (`entity` / `details` / optional `reviews` extras). STATUS_NORMALIZED was null on **64** unmapped CaseStatus values — all FILLED — and **2** Superseded rows incorrectly labeled Final were FIXED to Inactive. FILE_DATE and PERMIT_DATE already matched `ApplyDate` / `IssueDate` whenever present (**0** value changes). FINAL_DATE cleared **121** spurious non-Final stamps (mostly Active `Issued` carrying `FinalDate`). After repair: status complete; Final FINAL_DATE **94.7%**; Active/Final PERMIT_DATE **100% / 97.3%**. Remaining gaps are blank EnerGov issuance/final stamps with no alternate dates in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Kissimmee, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_kissimmee.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_kissimmee_repaired.parquet`

## DATA schema

All rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 61 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Variants are classified by which canonical dates are populated:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,047 | Issued + Finaled |
| `energov_issued` | 509 | Issued, no Finaled |
| `energov_applied` | 379 | Apply only |
| `energov_full_issued` | 42 | full keyset, issued |
| `energov_full_applied` | 17 | full keyset, apply only |
| `energov_finaled` | 4 | Finaled, no IssueDate |
| `energov_full_issued_finaled` | 2 | full keyset, issued + finaled |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active/Final/Inactive |
| FINAL_DATE | `entity.FinalDate` (fallback `details.FinalizeDate`) for Final only |

CaseStatus → normalized (high level): Finaled / Certificate of Occupancy / Certificate of Completion / Closed / Masterfile Closed → Final; Issued / ROW Utilization Issued → Active; In Review / Submitted-Online / Fees Paid / Fees Due / On Hold / Pending Permit Issuance / Approved-Pending Main Permit Issuance / Insufficient Submittal / Revision Fees Due / Extension/Reinstatement Fees Due → In Review; Expired / Void / Canceled / Abandoned (Closed) / Disapproved Review / Masterfile Expired / On Hold-Expired Certifications/Registration / On Hold-Main Permit Expired / Superseded → Inactive. `CaseStatus` and `details.PermitStatus` always agree in this sample.

## Field assessments

### STATUS_NORMALIZED

Upstream distribution: Final 981 · Inactive 682 · Active 239 · In Review 34 · **null 64**.

The 64 nulls are unmapped `STATUS_ORIGINAL` / CaseStatus values:

| CaseStatus | n | → |
| --- | ---: | --- |
| Submitted-Online | 13 | In Review |
| ROW Utilization Issued | 13 | Active |
| Disapproved Review | 12 | Inactive |
| Abandoned (Closed) | 7 | Inactive |
| Pending Permit Issuance | 7 | In Review |
| Masterfile Closed | 5 | Final |
| Approved-Pending Main Permit Issuance | 2 | In Review |
| On Hold-Main Permit Expired | 2 | Inactive |
| Insufficient Submittal | 1 | In Review |
| Revision Fees Due | 1 | In Review |
| Extension/Reinstatement Fees Due | 1 | In Review |

**2 FIXED:** Superseded was incorrectly Final → Inactive (`BP-06-01885`, `BP-20-02311`).

After: Final 984 · Inactive 705 · Active 252 · In Review 59 · null **0**.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. When both present (2,000 rows), FILE_DATE always equals `ApplyDate` (**0 FILLED / 0 FIXED**).
- Coverage after repair: **100%** across all statuses.
- One agency quirk remains: ApplyDate after IssueDate on Final `BP-05-02383` (Certificate of Occupancy) — FILE_DATE > PERMIT_DATE. Left as-is.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When IssueDate and PERMIT_DATE were both present, they always matched (**0 FILLED / 0 FIXED**). Missing PERMIT_DATE always mirrored blank IssueDate.
- Active/Final still missing PERMIT_DATE: **27** = Closed (20) + Masterfile Closed (4) + Finaled (3) with null IssueDate. Not inventable from DATA (`CompleteDate` / `ClosedDate` always null).
- Two In Review rows retain PERMIT_DATE after issuance-then-fees-due statuses (`Revision Fees Due`, `Extension/Reinstatement Fees Due`).

Coverage after repair: Active 252/252 (100%); Final 957/984 (97.3%); In Review 2/59; Inactive 389/705 (55.2%, issued-then-expired/voided/cancelled).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Existing FINAL_DATE values that matched `FinalDate` were already correct on Final rows (**0 FILLED**).
- **121 FIXED clears** of non-Final FINAL_DATE:
  - Active Issued carrying FinalDate (119) — agency stamp without Finaled/CO/Closed status
  - Inactive On Hold-Expired Certifications/Registration (1)
  - Abandoned (Closed) → Inactive (1)
- Remaining Final gap: **52** = Closed (47) + Masterfile Closed (5) with null `FinalDate` / `FinalizeDate`. No alternate final date in DATA.
- PERMIT_DATE > FINAL_DATE inversions after repair: **2** (Finaled shells with IssueDate after FinalDate; left as-is).

Coverage after repair: Final 932/984 (94.7%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 64 | 2 | 64 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 400 → 400 |
| FINAL_DATE | 0 | 121 | 947 → 1,068 |

Residual mismatches vs EnerGov CaseStatus / ApplyDate / IssueDate / FinalDate (for applicable statuses): **0**. Date-order checks after repair: FILE_DATE > PERMIT_DATE inversions **1**; PERMIT_DATE > FINAL_DATE inversions **2** (unrepairable agency quirks).
