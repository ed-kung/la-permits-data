# Upland (CA) data repair

**Summary:** Assessed Upland's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_upland.py`. Tyler EnerGov `entity`/`details` is the canonical source. Fixed 101 mislabeled statuses (Submitted/Issued/Approved/On Hold with IssueDate → Active; Finaled/Issued-with-FinalizeDate → Final; Expired/Voided → Inactive). FILE_DATE already complete and correct. Filled 13 missing PERMIT_DATEs from IssueDate. Cleared 58 junk FINAL_DATEs on non-Final rows and filled 10 Final FINAL_DATEs (9 from FinalDate/FinalizeDate on promotions; 1 from a Final Building inspection). After repair: status complete; Active PERMIT_DATE 100%; Final PERMIT_DATE 99.7% / FINAL_DATE 100%.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Upland, CA**.

## DATA schema

All 2,000 rows have DATA. Top-level keys are always `fees`, `entity`, `details`, `contacts`, `processing_status`, with an optional reviews bundle. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,779 | entity + details + contacts + fees + processing_status |
| `entity_fees_reviews` | 221 | plus reviews / holds / attachments / more_info |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` (+ FinalDate / IssueDate overrides) → `STATUS_NORMALIZED`
- `entity.ApplyDate` → `FILE_DATE`
- `entity.IssueDate` → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`, then Final* `processing_status` with status Final/Passed/Approved) → `FINAL_DATE`

Upland-specific CaseStatus labels include `Online Submission`, `On Hold/Pending`, `Plan Check`, `Revoked`, and `Refunded` (mapped In Review / Inactive as appropriate).

## Findings by field

### STATUS_NORMALIZED

Before: Inactive 675; Final 559; Active 449; In Review 317; missing 0.

Incorrect status causes:

1. **Issued / Approved / Submitted / On Hold/Pending / Online Submission with IssueDate** (78) left In Review → FIXED to Active. Includes 60 over-the-counter `Submitted` shells with `Issued=True` (e.g. yard sales) and 8 `Issued` shells whose `STATUS_ORIGINAL` lagged behind CaseStatus.
2. **Finaled left Active** (5, `STATUS_ORIGINAL=issued`) → FIXED to Final.
3. **Issued with PermitStatus=Finaled and FinalizeDate > IssueDate** (4) left Active → FIXED to Final.
4. **Issued with FinalDate strictly after IssueDate** (3) left Active → FIXED to Final.
5. **Stop Work Order with FinalDate > IssueDate** (3) left In Review → FIXED to Final.
6. **Expired left Active** (5, plus 1 Issued/Expired PermitStatus) → FIXED to Inactive.
7. **Voided left In Review** (1) → FIXED to Inactive.
8. **On Hold/Pending left Inactive** (1, `STATUS_ORIGINAL=denied`) with IssueDate → FIXED to Active.

Inactive labels (Expired / Voided / Cancelled / Denied / Revoked / Refunded) are sticky even when FinalDate is present as a case-closure stamp. Issued shells with FinalDate equal to or before IssueDate stay Active — same-day / inverted stamps are not treated as completion.

### FILE_DATE

Before: 0 missing. Every row's FILE_DATE matches `entity.ApplyDate` at calendar-day resolution. No repairs.

44 source chronology quirks remain where ApplyDate is after IssueDate (typically one calendar day); both dates match DATA, so left as-is.

### PERMIT_DATE

Before: 312 missing. Existing PERMIT_DATE always matched IssueDate when both present (0 mismatches). Gaps filled:

- Active/In Review Issued or Approved shells missing PERMIT_DATE while IssueDate present (13) → FILLED (rows also promoted to Active/Final as appropriate).

Remaining Active/Final gaps after repair (2): Finaled shells with null IssueDate in both entity and details — not fillable.

After repair: Active 510/510 (100%); Final 572/574 (99.7%). In Review PERMIT_DATE coverage is 0% by design (no IssueDate on remaining review rows).

### FINAL_DATE

Before: 1,378 missing (1 on Final). Existing FINAL_DATE matched FinalDate when both present, but 64 non-Final rows carried spurious FINAL_DATE (Inactive 52, Active 9, In Review 3).

Repairs:

1. **Cleared junk FINAL_DATE** on rows that stay non-Final (58) — Voided/Refunded/Cancelled/Denied closure stamps; Issued with FinalDate ≤ IssueDate; Approved same-day stamps.
2. **FILLED** FinalDate/FinalizeDate on 9 Issued/Finaled → Final promotions that were missing FINAL_DATE.
3. **FILLED** one Finaled shell (`B202200537`) from a Final Building inspection with status `Final` (2023-11-30).

After repair: Final FINAL_DATE 574/574 (100%); non-Final FINAL_DATE 0.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 101 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 13 | 0 | 312 → 299 |
| FINAL_DATE | 10 | 58 | 1,378 → 1,426 |

(Missing FINAL_DATE rises because junk non-Final stamps were cleared.)

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_upland.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_upland_repaired.parquet`
