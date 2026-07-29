# Poway (CA) data repair

**Summary:** Poway was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Tyler EnerGov `DATA` JSON (`entity` / `details`). Status: **FILLED 16 · FIXED 25** (null intake shells → In Review; stale `STATUS_ORIGINAL`-driven labels corrected from `CaseStatus` + date evidence). `FILE_DATE` already matched `ApplyDate` for all 1,999 rows (**FILLED/FIXED 0**). `PERMIT_DATE` missingness fell **322 → 320** (**FILLED 2**). `FINAL_DATE` missingness fell **621 → 615** (**FILLED 8 · FIXED 2**); after repair every non-Final row has null `FINAL_DATE`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Poway, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_poway.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_poway_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `entity`, `details`, `contacts`, `fees`, `processing_status`. A minority also carry a reviews bundle:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,926 | Core EnerGov payload |
| `entity_fees_reviews` | 73 | Plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` / `details.PermitStatus`, with date upgrades from IssueDate / FinalDate / FinalizeDate |
| `FILE_DATE` | `entity.ApplyDate` (details fallback) |
| `PERMIT_DATE` | `entity.IssueDate` (details fallback) |
| `FINAL_DATE` | `entity.FinalDate`; else `details.FinalizeDate` |

`CaseStatus` and `details.PermitStatus` agree on every sample row. Upstream `STATUS_ORIGINAL` sometimes lags `CaseStatus` (e.g. `expired` while CaseStatus is already `Finaled`).

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,384 · Inactive 319 · Active 154 · In Review 126 · missing 16

Most rows already match a CaseStatus map (`Finaled`/`Complete`→Final, `Issued`/`Active`→Active, `Expired`/`Void`/`Withdrawn`/`Denied`/`Inactive`→Inactive, review/intake/fees labels→In Review). Repairable problems:

1. **Null status on intake / awaiting-response shells (16).** CaseStatus values like `Submitted Online - Intake`, `Plan/Eng Intake Awaiting Applicant Response`, `In Review` were left unmapped upstream → **FILLED** as In Review.
2. **Stale labels vs live CaseStatus / dates (25 FIXED):**
   - In Review → Final (10): Fees Paid / Finaled shells with credible FinalDate (upstream still had `fees due` / `fees paid`).
   - Inactive → Final (6): Finaled (5) or Fees Paid+FinalDate (1) left Inactive because `STATUS_ORIGINAL` was `expired`.
   - In Review → Active (4): Issued (2) or Fees Paid with IssueDate but no FinalDate (2).
   - Active → Final (3): Finaled (1) or Issued+FinalDate (2).
   - Active → Inactive (2): CaseStatus Expired left Active because `STATUS_ORIGINAL` was `issued`.

| Change | n | Reason |
| --- | ---: | --- |
| nan → In Review | 16 | Unmapped intake / awaiting labels |
| In Review → Final | 10 | Fees Paid / Finaled + FinalDate |
| Inactive → Final | 6 | Finaled / Fees Paid+FinalDate, stale expired |
| In Review → Active | 4 | Issued / Fees Paid + IssueDate |
| Active → Final | 3 | Finaled or Issued+FinalDate |
| Active → Inactive | 2 | Expired |

Inactive terminal labels (`Expired`, `Void`, `Withdrawn`, `Denied`, `Inactive`) are sticky even when FinalDate is present as a closure stamp.

**After:** Final 1,403 · Inactive 315 · Active 153 · In Review 128 · missing 0  
Flags: **FILLED 16 · FIXED 25**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` already equals `entity.ApplyDate` at day resolution.
- `details.ApplyDate` can differ by one calendar day due to timezone encoding (12 rows); entity ApplyDate is the canonical source and matches `FILE_DATE`.
- No fills or fixes needed.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 322 missing (16.1%).

Root causes:
1. Two Issued shells labeled In Review had IssueDate but null `PERMIT_DATE` → status FIXED to Active and **FILLED 2**.
2. Wherever IssueDate was present and `PERMIT_DATE` populated, dates already matched (0 day mismatches).
3. Remaining Active/Final gaps have null `IssueDate` and `details.Issued=false` in DATA — not repairable.

**After:** 320 missing. Active 107/153 (69.9%); Final 1,360/1,403 (96.9%); In Review 0/128.

Remaining Active/Final gaps by CaseStatus: Finaled 32 · Issued 23 · Active 23 · Complete 11.  
Active gaps concentrate in `Vegetation Management` (23) and `Converted - Converted` (20) shells with no issuance stamp.

Flags: **FILLED 2 · FIXED 0**

### FINAL_DATE

**Before:** 621 missing (31.1%). Among Final: 19 missing with FinalDate available on 7 of those (plus status-promoted rows).

Root causes:
1. Status-promoted Final rows (and a few Finaled left Active/Inactive) had FinalDate but null `FINAL_DATE` → **FILLED 8**.
2. Spurious `FINAL_DATE` on Inactive shells (case-closure stamps on Inactive/Withdrawn) → **FIXED 2** (cleared).
3. 19 Final rows still lack FinalDate/FinalizeDate in DATA (Finaled 13 · Complete 6) → not repairable.

Wherever FinalDate was present and `FINAL_DATE` populated, dates already matched. `ExpireDate` is not used.

**After:** 615 missing. Final 1,384/1,403 (98.6%); Active / In Review / Inactive all 0% (spurious stamps cleared or status promoted).  
Flags: **FILLED 8 · FIXED 2**

## Chronology

After repair, agency-sourced date inversions remain in DATA (not introduced by repair):

- `FILE > PERMIT`: 2 (IssueDate before ApplyDate on Finaled fire/special-event shells)
- `PERMIT > FINAL`: 1 (FinalDate before IssueDate on a Finaled re-roof)

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 16 | 25 | 16 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 2 | 0 | 322 → 320 |
| `FINAL_DATE` | 8 | 2 | 621 → 615 |
