# Temecula (CA) data repair

**Summary:** Assessed Temecula's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_temecula.py`. Temecula uses a Tyler EnerGov portal payload (`entity` + `details`). The repair fills 1 missing status and fixes 19 stale ones (mostly STATUS_ORIGINAL lagging CaseStatus), fills 9 PERMIT_DATEs and fixes 1 stale issuance date, fills 8 FINAL_DATEs on newly promoted Final rows, and clears 1 spurious FINAL_DATE on Expired. After repair, FILE_DATE is 100% populated, Active has 99.4% PERMIT_DATE, and Final has 96.6% FINAL_DATE / 94.6% PERMIT_DATE. Remaining gaps are Finaled/Issued shells with null IssueDate or FinalDate in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Temecula, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,792 | `entity` + `details` + `contacts` + `fees` + `processing_status` |
| `entity_fees_reviews` | 167 | Above plus `reviews` / `holds` / `attachments` / `more_info` |
| `entity_basic` | 41 | `entity` + `details` + `contacts` + `processing_status` (no fees) |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` → `STATUS_NORMALIZED` (with IssueDate / credible FinalDate overrides)
- `entity.ApplyDate` (fallback `details.ApplyDate`) → `FILE_DATE`
- `entity.IssueDate` (fallback `details.IssueDate`) → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`) → `FINAL_DATE`

`ExpireDate` is a validity window, not a completion date. `CompleteDate` / `ClosedDate` are unused (always null in the sample).

Temecula CaseStatus vocabulary: Finaled, Issued, Applied, In Plancheck, Out, Ready for Issuance, Pending Approvals, Expired, Expired - Plan Check, Void, Cancel.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,135 / Inactive 442 / In Review 256 / Active 166 / missing 1.

Root cause: `STATUS_ORIGINAL` (and thus `STATUS_NORMALIZED`) often lags the live `entity.CaseStatus` / `details.PermitStatus` in DATA.

Issues:

1. **Missing (1):** `Pending Approvals` → FILLED In Review.
2. **Incorrect / stale (19 after repair):**
   - 7 `Finaled` shells left Active (4), In Review (2), or Inactive (1) → Final.
   - 1 `Issued` shell with `PermitStatus=Finaled` (FinalizeDate present) left Active → Final.
   - 9 `Issued` shells (and 1 Applied/`PermitStatus=Issued` with details IssueDate) left In Review → Active.
   - 1 Void and 1 Cancel left In Review → Inactive.

Repair performance: **1 FILLED, 19 FIXED**; missing after: **0**.

After: Final 1,143 / Inactive 443 / In Review 244 / Active 170.

### FILE_DATE

Before: 0 missing. All 2,000 FILE_DATE values match `entity.ApplyDate` at calendar-day resolution.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 100%.

Two FILE > PERMIT day inversions remain in source DATA (ApplyDate just after midnight UTC vs IssueDate prior calendar day) — not corrected; timestamps match DATA.

### PERMIT_DATE

Before: 440 missing. Where both present, PERMIT_DATE matches IssueDate on 1,559/1,560 rows; one stale In Review/`Finaled` row had PERMIT_DATE 2024-07-03 while IssueDate is 2024-08-14 → FIXED.

Repair: **9 FILLED** (IssueDate present on newly Active/Final rows), **1 FIXED**.

Remaining Active/Final gap: **63** (Finaled 62, Issued 1) — all lack IssueDate in DATA (Fire hourly inspections, temporary signs, special events, plus one Issued shell with blank IssueDate). Active coverage after repair: **169 / 170 (99.4%)**; Final: **1,081 / 1,143 (94.6%)**.

### FINAL_DATE

Before: 903 missing. All populated FINAL_DATE values matched FinalDate. **1 non-Final** Expired row carried FINAL_DATE from a case-closure stamp → cleared. Separately, 8 shells promoted to Final carried FinalDate/FinalizeDate but null FINAL_DATE → FILLED.

Repair: **8 FILLED**, **1 FIXED** (cleared Expired closure stamp).

Final coverage after repair: **1,104 / 1,143 (96.6%)**. The remaining **39** Finaled rows have null FinalDate and null FinalizeDate in DATA (mostly older Fire / Temporary Sign / Special Event cases) — not fillable. No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_temecula.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky (Expired / Expired - Plan Check / Void / Cancel); Finaled/Complete/Closed from CaseStatus **or** PermitStatus → Final; FinalDate/FinalizeDate credible only if Finaled label **or** stamp strictly after IssueDate; else IssueDate → Active; else CaseStatus map (Applied / In Plancheck / Out / Ready for Issuance / Pending Approvals → In Review).

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 1 | 19 | 1 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 9 | 1 | 440 | 431 |
| FINAL_DATE | 8 | 1 | 903 | 896 |

### Ideal coverage after repair

| Check | Coverage |
| --- | --- |
| FILE_DATE any status | 2,000 / 2,000 (100%) |
| PERMIT_DATE Active | 169 / 170 (99.4%) |
| PERMIT_DATE Final | 1,081 / 1,143 (94.6%) |
| FINAL_DATE Final | 1,104 / 1,143 (96.6%) |
| Spurious FINAL_DATE on non-Final | 0 |

## Artifact

- Script: `agent/scripts/ca/data_repair_ca_temecula.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_temecula_repaired.parquet`
