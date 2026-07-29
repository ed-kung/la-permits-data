# Laguna Hills (CA) data repair

**Summary:** Assessed Laguna Hills's 2,001-row sample and wrote `agent/scripts/ca/data_repair_ca_laguna_hills.py`. Tyler EnerGov `entity`/`details` is the canonical source (case-insensitive CaseStatus matching for `FINALED` / `CANCELLED` / `READY TO ISSUE`). Status, FILE_DATE, and PERMIT_DATE were already correct relative to DATA. Cleared 2 junk FINAL_DATEs on Inactive Void/Expired rows (case-closure stamps). After repair: status complete; Active PERMIT_DATE 92.6%; Final PERMIT_DATE 99.8% / FINAL_DATE 99.2%.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Laguna Hills, CA**.

## DATA schema

All 2,001 rows have DATA. Top-level keys are always `fees`, `entity`, `details`, `contacts`, `processing_status`, with an optional reviews bundle. `processing_status` is null on every sample row. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,969 | entity + details + contacts + fees + processing_status |
| `entity_fees_reviews` | 32 | plus reviews / holds / attachments / more_info |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` → `STATUS_NORMALIZED`
- `entity.ApplyDate` → `FILE_DATE`
- `entity.IssueDate` → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`, then passed Final* `processing_status`) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before/after: Final 1,466; Inactive 400; Active 95; In Review 40; missing 0.

Every CaseStatus maps cleanly under case-insensitive rules:

| CaseStatus | STATUS_NORMALIZED | N |
| --- | --- | --- |
| Complete | Final | 1,115 |
| FINALED | Final | 351 |
| Expired | Inactive | 357 |
| Void | Inactive | 28 |
| CANCELLED | Inactive | 12 |
| Plan Approval Expired | Inactive | 3 |
| Issued | Active | 95 |
| In Review | In Review | 21 |
| Submitted - Online | In Review | 8 |
| READY TO ISSUE | In Review | 7 |
| Application Incomplete | In Review | 3 |
| On Hold | In Review | 1 |

No Issued shells carry FinalDate, so no Active→Final promotions. Inactive labels stay sticky even when FinalDate is present as a closure stamp. No STATUS repairs.

### FILE_DATE

Before: 0 missing. Every row's FILE_DATE matches `entity.ApplyDate` at calendar-day resolution. No repairs.

Eight source chronology quirks remain where ApplyDate is after IssueDate; both dates match DATA, so left as-is.

### PERMIT_DATE

Before: 91 missing. Existing PERMIT_DATE always matched IssueDate when both present (0 mismatches). Gaps on Active/Final after repair:

- Active Issued with `Issued=False` and null IssueDate (7) → not fillable.
- FINALED with null IssueDate (3) → not fillable.

After repair: Active 88/95 (92.6%); Final 1,463/1,466 (99.8%). No FILLED/FIXED on PERMIT_DATE.

### FINAL_DATE

Before: 544 missing (11 on Final). Existing FINAL_DATE matched FinalDate when both present. Two Inactive rows carried spurious FINAL_DATE (Void / Expired closure stamps).

Repairs:

1. **Cleared junk FINAL_DATE** on Void `CO-10-13-8175` and Expired `PL-8-18-17096` (2 FIXED).

Remaining Final FINAL_DATE gaps (11) are FINALED (10) / Complete (1) shells with null FinalDate/FinalizeDate and null `processing_status` — not fillable from DATA. ExpireDate is a validity window, not used.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 91 → 91 |
| FINAL_DATE | 0 | 2 | 544 → 546 |

(Missing FINAL_DATE rises because junk non-Final stamps were cleared.)

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_laguna_hills.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_laguna_hills_repaired.parquet`
