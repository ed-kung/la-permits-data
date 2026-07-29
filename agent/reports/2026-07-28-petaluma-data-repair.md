# Petaluma (CA) data repair

**Summary:** Petaluma was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed 2,000 Tyler EnerGov records against `DATA`. Main defects: 3 unmapped `Utility Restoration` statuses (null); 19 stale statuses on issued/finaled shells still labeled Issued / Fees Due / Fees Paid / In Review; and 60 spurious `FINAL_DATE` stamps on Inactive (Void/Expired) rows from case-closure `FinalDate`. Repair fills all 3 missing statuses, fixes the 19 stale ones, and clears those 60 finals. `FILE_DATE` already matched `ApplyDate` everywhere. Residual gap: 152 Complete/Final rows with no `IssueDate` (mostly encroachment / utility / tree-removal) → `PERMIT_DATE` stays missing. Script: `agent/scripts/ca/data_repair_ca_petaluma.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in sample order without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Petaluma, CA** (2,000 rows).

## DATA schema

All rows share Tyler EnerGov top-level keys. Canonical dates/status live under `entity` with `details` fallbacks (`CaseStatus` / `PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` / `FinalizeDate`). Content variants in `INFERRED_SCHEMA`:

| Schema | n | Keys |
| --- | ---: | --- |
| `entity_fees` | 1,923 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 77 | above + reviews / holds / attachments / more_info |

`ExpireDate` is a validity window, not completion. `processing_status` lists inspections but were not needed for date repair in this sample. When both present, `entity.FinalDate` and `details.FinalizeDate` agree on every row (1,334 / 1,334).

## Field assessment

### STATUS_NORMALIZED

Before repair: Final 1,266 / Inactive 371 / Active 228 / In Review 132 / missing 3.

| CaseStatus | Before STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Complete | Final | 1,266 |
| Expired / Void / Denied | Inactive | 371 |
| Issued | Active | 228 |
| In Review / Fees Due / Fees Paid / On Hold / Incomplete / Ready to Issue / Submitted - Online | In Review | 132 |
| Utility Restoration | missing | 3 |

Issues:

- **3** `Utility Restoration` rows had null STATUS_NORMALIZED; all are issued with no FinalDate → Active (FILLED).
- **4** `Issued` / Active rows already carry `FinalDate` (status stamp stale) → Final (FIXED).
- **5** `Fees Due` / In Review rows with `FinalDate` (and IssueDate; UnPaidFees false) → Final (FIXED).
- **10** review-pipeline rows with IssueDate but no FinalDate (Fees Due 6, Fees Paid 2, In Review 2) → Active (FIXED).
- Inactive terminal labels (Expired / Void / Denied) are sticky even when `FinalDate` is present as a case-closure stamp.

### FILE_DATE

2,000 / 2,000 populated. Every FILE_DATE matches `entity.ApplyDate` at UTC calendar-day resolution (0 mismatches). **No FILE_DATE repairs.**

### PERMIT_DATE

Where both exist, PERMIT_DATE matches `IssueDate` (0 mismatches). Gaps:

- All Active rows already had PERMIT_DATE (including the 3 Utility Restoration and the 10 promoted from In Review).
- **152** Final/`Complete` rows with null IssueDate (54 sidewalk/misc encroachment, 52 utility encroachment, 43 tree removal, 2 legacy, 1 residential solar) → not fillable; DATA has no alternate issuance stamp.
- After promoting 9 issued shells into Final, Final PERMIT coverage is 1,123 / 1,275 (88.1%).

Ten pre-existing FILE_DATE > PERMIT_DATE day inversions remain (ApplyDate one UTC calendar day after IssueDate); not introduced by repair.

### FINAL_DATE

All Final rows already had FINAL_DATE matching FinalDate/FinalizeDate (including the 9 promoted into Final). Incorrect values:

- **59** Void and **1** Expired Inactive rows carried FINAL_DATE from case-closure `FinalDate` → cleared (FIXED).
- The 4 Active and 5 In Review rows that previously carried FINAL_DATE were promoted to Final and retained the stamp.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_petaluma.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_ca_petaluma_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 19 | 3 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 386 → 386 |
| FINAL_DATE | 0 | 60 | 665 → 725 |

Status transitions:

- nan → Active: 3
- Active → Final: 4
- In Review → Final: 5
- In Review → Active: 10

After-repair coverage:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active (237) | 237 / 237 (100%) | 0 / 237 |
| Final (1,275) | 1,123 / 1,275 (88.1%) | 1,275 / 1,275 (100%) |
| In Review (117) | 0 / 117 | 0 / 117 |
| Inactive (371) | 254 / 371 | 0 / 371 |

FILE_DATE: 2,000 / 2,000 (100%). Chronology: 10 pre-existing FILE > PERMIT day inversions; 0 PERMIT > FINAL.
