# Yucaipa (CA) data repair

**Summary:** Assessed Yucaipa's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_yucaipa.py`. Tyler EnerGov `entity`/`details` is the canonical source. Filled 2 missing statuses (`Pending Master Plan Approval` → In Review) and fixed 46 mislabeled ones (Issued/Fees Due/Fees Paid with FinalDate → Final; Submitted/Fees* with IssueDate → Active). FILE_DATE already complete and correct. Cleared 42 junk FINAL_DATEs on non-Final rows and filled 3 Final FINAL_DATEs (2 from FinalizeDate on Issued→Final promotions; 1 from a passed Final* inspection). After repair: status complete; Active PERMIT_DATE 83.8%; Final PERMIT_DATE 98.8% / FINAL_DATE 99.0%.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Yucaipa, CA**.

## DATA schema

All 2,000 rows have DATA. Top-level keys are always `fees`, `entity`, `details`, `contacts`, `processing_status`, with an optional reviews bundle. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,925 | entity + details + contacts + fees + processing_status |
| `entity_fees_reviews` | 75 | plus reviews / holds / attachments / more_info |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` (+ FinalDate / IssueDate overrides) → `STATUS_NORMALIZED`
- `entity.ApplyDate` → `FILE_DATE`
- `entity.IssueDate` → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`, then passed Final* `processing_status`) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Inactive 1,191; Final 485; In Review 177; Active 145; missing 2.

Missing status causes:

1. **Unmapped label** (2) — `Pending Master Plan Approval` left null upstream → FILLED as In Review.

Incorrect status:

1. **Issued with FinalDate/FinalizeDate strictly after IssueDate** (15, including 2 with `PermitStatus=Finaled`) left Active → FIXED to Final.
2. **Fees Due / Fees Paid with FinalDate > IssueDate** (19) left In Review → FIXED to Final.
3. **Submitted / Fees Due / Fees Paid with IssueDate but no credible FinalDate** (12) left In Review → FIXED to Active.

Inactive labels (Expired / Void / Withdrawn) are sticky even when FinalDate is present as a case-closure stamp. Issued shells with FinalDate equal to IssueDate (2) stay Active — same-day stamps are not treated as completion.

### FILE_DATE

Before: 0 missing. Every row's FILE_DATE matches `entity.ApplyDate` at calendar-day resolution. No repairs.

Two source chronology quirks remain where ApplyDate is after IssueDate (Fees Due revision / Issued shell); both dates match DATA, so left as-is.

### PERMIT_DATE

Before: 432 missing. Existing PERMIT_DATE always matched IssueDate when both present (0 mismatches). Gaps on Active/Final after repair:

- Active Issued with `Issued=False` and null IssueDate (23) — mostly legacy 2007–2008 CityView shells → not fillable.
- Finaled / Complete with null IssueDate (6) → not fillable.

After repair: Active 119/142 (83.8%); Final 513/519 (98.8%). No FILLED/FIXED on PERMIT_DATE — rows promoted to Active/Final already carried IssueDate-backed PERMIT_DATE.

### FINAL_DATE

Before: 1,447 missing (6 on Final). Existing FINAL_DATE matched FinalDate when both present, but 74 non-Final rows carried spurious FINAL_DATE (Inactive 39, Active 15, In Review 20).

Repairs:

1. **Cleared junk FINAL_DATE** on rows that stay non-Final (42) — Expired/Void closure stamps, Issued with FinalDate ≤ IssueDate, Fees Due with FinalDate but no IssueDate.
2. **FILLED** FinalizeDate on 2 Issued→Final promotions that were missing FINAL_DATE.
3. **FILLED** one Finaled shell from passed Final Electrical/Mechanical/Plumbing inspections (2012-06-08).

Remaining Final FINAL_DATE gaps (5) are Finaled shells with neither FinalDate/FinalizeDate nor a usable Final* inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 2 | 46 | 2 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 432 → 432 |
| FINAL_DATE | 3 | 42 | 1,447 → 1,486 |

(Missing FINAL_DATE rises because junk non-Final stamps were cleared.)

After repair coverage:

| Status | N | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- | --- |
| Active | 142 | 100% | 83.8% | 0% |
| Final | 519 | 100% | 98.8% | 99.0% |
| In Review | 148 | 100% | 0% | 0% |
| Inactive | 1,191 | 100% | 78.6% | 0% |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_yucaipa.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_yucaipa_repaired.parquet`
