# Atascadero (CA) data repair

**Summary:** Atascadero uses a civic-portal DATA schema (`permit_info` + `search_data`). STATUS_NORMALIZED was often derived from a stale `STATUS_ORIGINAL` / search_data mirror rather than live `PermitStatus`, leaving 19 rows mislabeled. FILE_DATE was already complete and correct. Repair filled 43 missing PERMIT_DATE values (Approved fallback) and 8 FINAL_DATE values; remaining gaps have no source dates in DATA.

## Scope

- Sample: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Atascadero, CA** (first `(JURISDICTION, STATE)` pair without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- N = 2,000 rows
- Script: `agent/scripts/ca/data_repair_ca_atascadero.py`
- Artifact: `AGENT_DATA_PATH/atascadero_repaired_sample.parquet`

## DATA schema

All rows share top-level keys: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`.

Canonical fields under `permit_info`:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `PermitStatus` (override to Final when `PermitFinaledDate` present and status not inactive) |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` / SD `Issued Date` / `Approved Date` |
| FINAL_DATE | `PermitFinaledDate` |

`INFERRED_SCHEMA` (by which dates are populated):

| Schema | N |
| --- | --- |
| permit_info_issued_finaled | 1,331 |
| permit_info_issued | 386 |
| permit_info_applied_only | 137 |
| permit_info_approved_only | 82 |
| permit_info_finaled_only | 64 |

`inspections` is empty for all sample rows; no inspection-based FINAL_DATE fallback is available.

## Field assessment

### STATUS_NORMALIZED

No missing values. Most rows already matched `PermitStatus`, but 19 were wrong because `STATUS_ORIGINAL` mirrored a stale search_data `Permit Status` (or older snapshot) instead of live `permit_info.PermitStatus`.

Examples:

- `PermitStatus=FINALED` with `STATUS_ORIGINAL=issued` → labeled Active
- `PermitStatus=ISSUED` with `STATUS_ORIGINAL=permit prep` / `received` → labeled In Review
- `APPROVED` / `ISSUED` rows that already have `PermitFinaledDate` → should be Final

**Repair:** 19 FIXED (In Review→Active: 6; Active→Final: 11; In Review→Final: 2). After repair: Final 1,415 / Active 287 / Inactive 228 / In Review 70.

### FILE_DATE

Already populated for all 2,000 rows and exact match to `PermitAppliedDate`. No FILLED / FIXED.

### PERMIT_DATE

291 missing before. For Active/Final, 88 were missing; 35 had `PermitApprovedDate` usable as fallback (Issued blank). Additional fills came from status FIXED rows that newly became Active/Final.

**Repair:** 43 FILLED. After: 248 still missing overall; **53 Active/Final** still missing, all with neither Issued nor Approved in DATA (not repairable).

Coverage after repair: Active 96.5%, Final 97.0%.

### FINAL_DATE

613 missing before. Among Final rows, 19 lacked FINAL_DATE and also lacked `PermitFinaledDate`. Four Active rows had FINAL_DATE because they had `PermitFinaledDate` — those were status-corrected to Final rather than clearing the date.

**Repair:** 8 FILLED (status-corrected Final rows that had `PermitFinaledDate` but blank FINAL_DATE). After: Final coverage **1,395 / 1,415 (98.6%)**. Remaining **20** are `FINALED` with blank `PermitFinaledDate` and empty inspections — not repairable.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 19 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 43 | 0 | 291 → 248 |
| FINAL_DATE | 8 | 0 | 613 → 605 |

## Not repairable

- 20 `FINALED` rows with no `PermitFinaledDate` and no inspections
- 53 Active/Final rows with neither Issued nor Approved dates
