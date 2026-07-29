# Danville (CA) data repair

**Summary:** Danville was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Tyler EnerGov `DATA` JSON (`entity` / `details`). Status: **FIXED 57** (Approved→In Review, Finaled/Issued+FinalizeDate→Final, Expired→Inactive, Issued→Active). `FILE_DATE` already matched `ApplyDate` for all 1,999 rows (**FILLED/FIXED 0**). `PERMIT_DATE` missingness fell **208 → 202** (**FILLED 6**). `FINAL_DATE` missingness fell **542 → 527** (**FILLED 17 · FIXED 3**); after repair every Final row has `FINAL_DATE` and every Active row has `PERMIT_DATE`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Danville, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_danville.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_danville_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `entity`, `details`, `contacts`, `fees`, `processing_status`. A minority also carry a reviews bundle:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,901 | Core EnerGov payload |
| `entity_fees_reviews` | 98 | Plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` / `details.PermitStatus`, with date upgrades from IssueDate / FinalDate / FinalizeDate |
| `FILE_DATE` | `entity.ApplyDate` (details fallback) |
| `PERMIT_DATE` | `entity.IssueDate` (details fallback) |
| `FINAL_DATE` | `entity.FinalDate`; else `details.FinalizeDate` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,454 · Inactive 302 · Active 183 · In Review 60 · missing 0

`CaseStatus` values are mostly well-mapped (`Finaled`→Final, `Issued`→Active, `Canceled`/`Withdrawn`/`Expired`/…→Inactive, review-pipeline labels→In Review). Repairable problems:

1. **Approved left Active (28).** Plan-approval without IssueDate; upstream treated Approved as issued. Remap to In Review.
2. **Finaled / Issued+FinalizeDate left Active (18).** CaseStatus Finaled (12) or stale Issued with `details.FinalizeDate` only (5), plus one Approved with FinalDate → Final; fill `FINAL_DATE`.
3. **Expired left Active (6).** Sticky Inactive.
4. **Issued left In Review (3).** Promote to Active; fill `PERMIT_DATE`.
5. **Canceled / Voided left In Review (2).** Sticky Inactive.

| Change | n | Reason |
| --- | ---: | --- |
| Active → In Review | 28 | Approved, no IssueDate |
| Active → Final | 18 | Finaled or credible FinalizeDate |
| Active → Inactive | 6 | Expired |
| In Review → Active | 3 | Issued + IssueDate |
| In Review → Inactive | 2 | Canceled / Voided |

**After:** Final 1,472 · Inactive 310 · Active 134 · In Review 83 · missing 0  
Flags: **FILLED 0 · FIXED 57**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` already equals `entity.ApplyDate` at day resolution.
- No fills or fixes needed.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 208 missing (10.4%). Among Active/Final: 32 / 38 missing.

Root causes:
1. Upstream left `PERMIT_DATE` null on a few Issued / Finaled shells that do carry `IssueDate` → **FILLED 6**.
2. 29 Active+Approved shells had no IssueDate (correct after status remap to In Review).
3. 38 Finaled rows (mostly older electrical) have null `IssueDate` and `details.Issued=false` → not repairable.

Wherever IssueDate was present and `PERMIT_DATE` populated, dates already matched (0 day mismatches).

**After:** 202 missing. Active 134/134 (100%); Final 1,433/1,472 (97.4%); In Review 0/83.  
Flags: **FILLED 6 · FIXED 0**

Remaining Active/Final gaps: 38 Finaled + 1 Approved-promoted Final (DEV13-0055, FinalDate present, no IssueDate).

### FINAL_DATE

**Before:** 542 missing. All Final rows already had `FINAL_DATE`; gaps were non-Final statuses plus 17 Active shells that already carried FinalDate/FinalizeDate in DATA.

Repairs:
1. **FILLED 17** — Active→Final promotions (Finaled / Issued+FinalizeDate) get FinalDate / FinalizeDate.
2. **FIXED 1** — SUB22-0009 day mismatch (`FINAL_DATE` 2023-02-24 vs entity FinalDate 2022-12-29) → overwrite from DATA.
3. **FIXED 2** — clear spurious FinalDate on Inactive Expired / Canceled (case-closure stamps).

**After:** 527 missing. Final 1,472/1,472 (100%); Active / In Review / Inactive all 0%.  
Flags: **FILLED 17 · FIXED 3**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 57 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 6 | 0 | 208 → 202 |
| FINAL_DATE | 17 | 3 | 542 → 527 |

Post-repair coverage targets:
- FILE_DATE: **100%**
- PERMIT_DATE on Active: **100%**; on Final: **97.4%** (agency IssueDate absent)
- FINAL_DATE on Final: **100%**

Chronology: 3 FILE>PERMIT and 2 PERMIT>FINAL day inversions remain; all are agency timestamp quirks (ApplyDate slightly after IssueDate, or FinalDate before IssueDate in source), not introduced by the repair.
