# Destin (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Destin**. DATA is a Tyler EnerGov payload (`entity` / `details` / `fees` / `processing_status`; 22 rows also carry `reviews` / `holds` / `attachments` / `more_info`). Upstream left 8 `STATUS_NORMALIZED` nulls (unmapped Decal statuses) and stored EnerGov’s `1900-01-01` missing-date sentinel in 13 `PERMIT_DATE` and 990 `FINAL_DATE` values. Present non-sentinel dates already matched `ApplyDate` / `IssueDate` / `FinalDate` at calendar-day resolution. The repair filled 8 statuses, cleared 21 bad `PERMIT_DATE` values (13 sentinels + 8 In Review), and fixed 1,066 `FINAL_DATE` values (576 cleared on non-Final, 220 sentinel→real final/inspection dates, 270 uncleared Final sentinels dropped). After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 100%/92.1%; Final FINAL_DATE 77.6%.

## Jurisdiction selection

Ordered `(STATE, JURISDICTION)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Destin, FL** → `agent/scripts/fl/data_repair_fl_destin.py` (2,001 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. A minority also include review extras:

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,109 | Issued + final (FinalDate or final inspection) |
| `energov_issued` | 672 | Issued, no usable final |
| `energov_finaled` | 120 | Final without issued |
| `energov_applied` | 78 | Apply only |
| `energov_full_*` | 22 | Same content splits with reviews/holds/attachments/more_info |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `ApplyDate` (entity, else details) |
| PERMIT_DATE | `IssueDate` (entity, else details); `1900-01-01` treated as null |
| FINAL_DATE | `FinalDate` / `FinalizeDate`, else latest passed final-ish `processing_status` inspection; `1900-01-01` treated as null |

## Field assessments

### STATUS_NORMALIZED

| CaseStatus / PermitStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Complete | 1,202 | Final | Correct |
| Issued | 585 | Active | Correct |
| Null and Void | 77 | Inactive | Correct |
| Expired | 65 | Inactive | Correct |
| Fees Due | 20 | In Review | Correct (even when `Issued=True`) |
| In Review | 11 | In Review | Correct |
| On Hold | 9 | In Review | Correct |
| Submitted - Online | 7 | In Review | Correct |
| Administratively Closed | 4 | Final | Correct (2 with real FinalDate) |
| Denied / Canceled | 4 / 4 | Inactive | Correct |
| Decal to be placed / Decal To Be Placed / Decal Ready | 4 / 3 / 1 | **null** | Fill → In Review (not issued) |
| Fees Paid / Submitted / Submittal Incomplete | 2 / 1 / 1 | In Review | Correct |
| Plan Approval Expired | 1 | Inactive | Correct |

**Root causes:**
1. Upstream mapper omitted Decal workflow labels (`Decal Ready`, `Decal to be placed` and case variants).
2. All other observed CaseStatus values were already mapped correctly; CaseStatus and PermitStatus always agree in this sample.

**Repair performance:** FILLED 8, FIXED 0; missing 8 → 0.

### FILE_DATE

- Before: missing on **0 / 2,001**. Present values match `entity.ApplyDate` at calendar-day resolution for every row.
- One row has `details.ApplyDate` one UTC day ahead of `entity.ApplyDate`; the stored `FILE_DATE` follows entity (preferred source) — left unchanged.
- Ideal coverage already 100% for every status class.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: NaN on **199 / 2,001**, plus **13** rows storing the `1900-01-01` sentinel (Inactive Null and Void / one In Review).
- Non-sentinel present values always matched `IssueDate` (0 calendar mismatches).
- Active already 100% populated. Final gaps (95) are `Complete` shells with blank `IssueDate` (but often a real `FinalDate`) — not fillable without inventing an issuance date.
- In Review had 8 real `IssueDate` values (mostly Fees Due after issuance) and 1 sentinel; cleared to match the Active/Final ideal for `PERMIT_DATE`.

**Repair performance:** FILLED 0, FIXED 21; NaN 199 → 220 (sentinel cleanup + In Review clears). Active coverage 100%; Final coverage 92.1%.

### FINAL_DATE

- Before: NaN on **219 / 2,001**, plus **990** rows storing `1900-01-01` (including 490 Final / Complete rows). EnerGov uses that timestamp as “no final date.”
- Non-sentinel present values matched `FinalDate` / `FinalizeDate` (0 mismatches).
- 32 Active `Issued` rows and many Inactive / In Review rows carried a real or sentinel `FINAL_DATE` despite non-Final status → cleared.
- Of 490 Final sentinels, 220 were replaced from a passed Final / CO-style `processing_status` inspection; 270 had no usable final source (268 Complete + 2 Administratively Closed) → cleared to null.
- Two Complete rows have `IssueDate` after `FinalDate` in the agency payload (left as-is; source inconsistency).

**Repair performance:** FILLED 0, FIXED 1,066 (576 non-Final clears + 220 sentinel→inspection/date + 270 Final sentinel clears). Final coverage 77.6% (936 / 1,206). Active / In Review / Inactive FINAL_DATE all 0% after cleanup.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_destin.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_destin_repaired.parquet`
