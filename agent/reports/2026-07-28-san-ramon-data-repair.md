# San Ramon (CA) data repair

**Summary:** San Ramon was the first sample jurisdiction lacking a repair script (2,000 rows; La Cañada Flintridge already covered by `data_repair_ca_la_canada_flintridge.py`). DATA is Tyler EnerGov (`entity` / `details`). Upstream left 23 `Plan Check Fee Due` statuses null, lagged 3 Issued shells that already had FinalDate/FinalizeDate (or PermitStatus=Complete), and left 2 issued review-pipeline shells as In Review. Repair fills/fixes all 28 status gaps, fills 1 missing `FINAL_DATE` on a promoted Final row, and clears 71 junk `FINAL_DATE` values on Void / Fees Due non-Final rows. `FILE_DATE` was already complete and correct; `PERMIT_DATE` already matched `IssueDate` wherever present. After repair: FILE_DATE 100%, Active PERMIT_DATE 100%, Final FINAL_DATE 100%; 58 Complete shells (mostly Impact Permit Fees) still lack IssueDate so PERMIT_DATE stays missing.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order (accent-normalized city slugs). The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **San Ramon, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Tyler EnerGov portal payload. Core keys: `entity`, `details`, `contacts`, `processing_status`. Optional `fees` and reviews bundle (`reviews` / `holds` / `attachments` / `more_info`) distinguish variants.

| Schema | n |
| --- | ---: |
| `entity_fees_reviews` | 984 |
| `entity_fees` | 955 |
| `entity_basic` | 61 |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus`; `ApplyDate` → FILE_DATE; `IssueDate` → PERMIT_DATE; `FinalDate` / `details.FinalizeDate` → FINAL_DATE.

## Field assessment

### STATUS_NORMALIZED

Before: Active 656 / Final 812 / In Review 346 / Inactive 163 / missing 23.

| DATA.CaseStatus | Upstream | Repair |
| --- | --- | --- |
| Plan Check Fee Due (23) | null | FILLED → In Review |
| Issued + FinalDate/FinalizeDate after IssueDate, or PermitStatus=Complete (3) | Active | FIXED → Final |
| Fees Due / In Review with IssueDate (2) | In Review | FIXED → Active |

All other CaseStatus labels (`Complete`, `Issued`, `In Review`, `Expired`, `Void`, `Submitted - Online`, `Fees Due`, `On Hold`, `Submitted`) already mapped correctly.

After: Active 655 / Final 815 / In Review 367 / Inactive 163 / missing 0.

### FILE_DATE

Fully populated. Every value equals `entity.ApplyDate` at calendar-day resolution. No FILLED/FIXED. Coverage remains 2,000 / 2,000.

### PERMIT_DATE

Wherever `IssueDate` exists (1,521 rows), `PERMIT_DATE` already matched at calendar-day resolution. No FILLED/FIXED. Active coverage is 100%. Final coverage is 757 / 815 (92.9%); the 58 gaps are `Complete` shells with null `IssueDate` / `details.Issued=False` (mostly Impact Permit Fees, plus REVISION / DEFERRED SUBMITTAL / landscape irrigation) — no issuance stamp in DATA.

### FINAL_DATE

`FinalDate` / `FinalizeDate` are the true finaling stamps when status is Final (885 rows had matching FINAL_DATE before repair; all 812 Complete rows already had FINAL_DATE). After promoting 3 Active→Final, 1 missing FINAL_DATE was filled from FinalizeDate; the other 2 already matched.

Junk FINAL_DATE on non-Final rows was cleared (FIXED 71):

- 58 Void (case-closure FinalDate, not permit finaling)
- 13 Fees Due impact-fee shells (often same calendar day as ApplyDate; still unpaid)

After repair: Final 815 / 815 (100%); absent on all non-Final.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_san_ramon.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_san_ramon_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 23 | 5 | 23 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 479 → 479 |
| FINAL_DATE | 1 | 71 | 1,115 → 1,185 |

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 100%; Final 92.9% (58 Complete without IssueDate)
- FINAL_DATE: Final 100%; absent on non-Final
