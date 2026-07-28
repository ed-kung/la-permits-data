# Belmont (CA) data repair

**Summary:** Belmont was the first `(JURISDICTION, STATE)` pair without an existing repair script (alphabetically after Berkeley / Beverly Hills / Burbank / Butte County / Calabasas / Carson / Claremont / … — first gap at **Belmont**). Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the civic-portal `DATA` JSON (`permit_info` / dict `inspections`). Status missingness fell **40 → 0** (**FILLED 40 · FIXED 175**): blank/`DUPLICATE/CANCELED` statuses filled from dates or cancel labels; `FINALED`/`APPROVED`+Finaled mislabeled Active → Final; Issued/Active/Approved* mislabeled In Review → Active; `EXPIRED` mislabeled Active → Inactive. `FILE_DATE` already matched `PermitAppliedDate` wherever Applied exists (**FILLED/FIXED 0**); 13 rows lack Applied. `PERMIT_DATE` missingness fell **493 → 287** (**FILLED 206**) via Approved when Issued blank for Active/Final. `FINAL_DATE` gained **FILLED 17** (PermitFinaledDate / passed FINAL inspections) and **FIXED 4** (cleared spurious dates on Inactive).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Belmont, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_belmont.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/belmont_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Unlike Atherton, `search_data` only carries Address / RECORDID / Permit Number (no date mirrors). Sub-schemas reflect which `permit_info` fields are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,164 | Issued + Finaled present |
| `permit_info_issued` | 346 | Issued present, Finaled blank |
| `permit_info_finaled_only` | 217 | Finaled present, Issued blank |
| `permit_info_applied_only` | 187 | Only Applied populated |
| `permit_info_approved_only` | 43 | Approved present, Issued/Finaled blank |
| `legacy_no_status` | 38 | Blank `PermitStatus` but dates present |
| `permit_info_empty_dates` | 5 | Status text, no usable dates |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (prefer Final when non-inactive and `PermitFinaledDate` present; blank status inferred from dates) |
| `FILE_DATE` | `PermitAppliedDate` only |
| `PERMIT_DATE` | `PermitIssuedDate`; else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest passed FINAL inspection (`Type` matching FINAL*, `Result` Approved/Finaled/…) |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,269 · Active 582 · Inactive 73 · In Review 36 · missing 40

`PermitStatus` values are mostly well-mapped already (`FINALED`→Final, `ACTIVE`/`ISSUED`/`APPROVED`/`ALARM PERMIT ISSUED`→Active, `IN REVIEW`/`PENDING`/`APPLIED ONLINE`→In Review, `INACTIVE`/`CANCELED`/`EXPIRED`/`WITHDRAWN`→Inactive). Repairable problems:

1. **Blank / cancel status (40 missing).** 38 blank `PermitStatus` shells (mostly early-2000s) plus 2 `DUPLICATE/CANCELED`. Infer Final when `PermitFinaledDate` present (9), Active when Issued/Approved present (2), In Review when only Applied (27), Inactive for cancel labels (2).
2. **Active → Final (164).** 12 `FINALED` and 152 `APPROVED` rows that already have `PermitFinaledDate` (upstream left status Active while often copying `FINAL_DATE`).
3. **In Review → Active (6).** `ISSUED` / `ACTIVE` / `APPROVED*` truncated labels (`APPROVED -- PER`, `APPROVED (BY BU`) left as In Review.
4. **In Review → Final (4).** `NO CALL FOR FIN` (and similar) with final semantics / finaled dates.
5. **Active → Inactive (1).** `EXPIRED` mislabeled Active.

| Change | n | Reason |
| --- | ---: | --- |
| null → In Review | 27 | Blank status + Applied only |
| null → Final | 9 | Blank status + Finaled date |
| null → Active | 2 | Blank status + Issued |
| null → Inactive | 2 | `DUPLICATE/CANCELED` |
| Active → Final | 164 | `FINALED` or Finaled date on non-inactive |
| In Review → Active | 6 | Issued / Active / Approved* |
| In Review → Final | 4 | NO CALL / final semantics |
| Active → Inactive | 1 | `EXPIRED` |

**After:** Final 1,446 · Active 425 · In Review 53 · Inactive 76 · missing 0  
Flags: **FILLED 40 · FIXED 175**

### FILE_DATE

**Before:** 13 missing (0.65%).

- Where present (1,987), `FILE_DATE` always equals `PermitAppliedDate` (day match).
- All 13 missing rows also lack Applied (8 `FINALED` with only Issued/Finaled; 5 `INACTIVE`/`ACTIVE` shells with no dates). Do not backfill application date from Issued — that would conflate filing with issuance.

**After:** still 13 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 493 missing (24.7%). Among Active/Final: 298 / 72 missing.

Root cause: upstream left `PERMIT_DATE` null when `PermitIssuedDate` was blank even if `PermitApprovedDate` was available. Wherever Issued was present, `PERMIT_DATE` already matched it (0 mismatches).

Repairs (Active / Final only after status repair):
1. Prefer `PermitIssuedDate`.
2. Else `PermitApprovedDate`.

| Change | n |
| --- | ---: |
| FILLED from Issued/Approved | 206 |

**After:** 287 missing (14.4%).  
Coverage: Active 309/425 (72.7%) · Final 1,381/1,446 (95.5%).

Not repairable: 116 Active (`ACTIVE` with neither Issued nor Approved) and ~65 Final with neither date.

### FINAL_DATE

**Before:** 621 missing. Among Final: 58 missing. Also 152 Active / 3 In Review / 4 Inactive carried a `FINAL_DATE` (mostly `APPROVED`+Finaled Active rows that should be Final, plus 4 Inactive close timestamps).

Repairs:
1. After status repair, keep/fill `FINAL_DATE` for Final from `PermitFinaledDate`, else passed FINAL inspection.
2. Clear `FINAL_DATE` on non-Final rows.

| Change | n | Reason |
| --- | ---: | --- |
| FILLED | 17 | Missing Final date from Finaled field or FINAL inspection |
| FIXED (clear) | 4 | Spurious Final date on Inactive |

**After:** 608 missing overall; Final coverage 1,392/1,446 (96.3%). Active / In Review / Inactive all have 0 `FINAL_DATE`.

Not repairable: 54 Final rows — mostly `NO FINAL CALL` (30) and `FINALED` (21) with blank `PermitFinaledDate` and no usable FINAL inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 40 | 175 | 40 → 0 |
| `FILE_DATE` | 0 | 0 | 13 → 13 |
| `PERMIT_DATE` | 206 | 0 | 493 → 287 |
| `FINAL_DATE` | 17 | 4 | 621 → 608 |

## Artifacts

- `agent/scripts/ca/data_repair_ca_belmont.py`
- `AGENT_DATA_PATH/belmont_repaired_sample.parquet`
