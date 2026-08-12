# Clermont (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Clermont was first. Its DATA is a uniform civic/eTRAKiT payload (`permit_info` / `search_data` / `inspections`). STATUS_NORMALIZED was wrong or null on 56 rows (stale Active vs FINALED/APPROVED/EXPIRED, CLOSED without finalization, etc.). FILE_DATE already matched `PermitAppliedDate` wherever both existed (4 unfillable blanks). PERMIT_DATE gained 40 fills from IssuedDate/ApprovedDate. FINAL_DATE gained 16 fills on rows corrected to Final, plus 1 clear of a spurious Active final stamp; Final coverage is 99.3% after repair.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Clermont, FL** (1,999 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_clermont.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/clermont_repaired_sample.parquet`

## DATA schema

All records share the same top-level keys (`contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`). Content variants (INFERRED_SCHEMA) reflect which canonical dates are populated:

| INFERRED_SCHEMA | n |
| --- | ---: |
| `civic_issued_finaled` | 1,484 |
| `civic_issued` | 284 |
| `civic_applied` | 211 |
| `civic_finaled` | 16 |
| `civic_status_only` | 4 |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (APPROVED gated on IssuedDate; CLOSED gated on a resolvable final stamp) |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate`, else search `FINALED`/`CO ISSUED`, else latest Approved final-ish inspection |

Only 10 rows carry inspections; search_data never has `FINALED`/`CO ISSUED` keys in this sample (date fallbacks rarely fire).

## Field assessments

### STATUS_NORMALIZED

4 missing before repair. Most rows already matched PermitStatus. **3 FILLED, 53 FIXED** (56 total changes):

| Before → After | PermitStatus | n |
| --- | --- | ---: |
| Active → In Review | APPROVED (no IssuedDate) | 20 |
| Active → Final | FINALED | 15 |
| Final → Inactive | CLOSED (no final stamp) | 10 |
| Active → Inactive | EXPIRED / REJECTED | 3 |
| In Review → Active | ISSUED | 2 |
| null → In Review | APPROVED PENDING | 2 |
| In Review → Final | FINALED | 1 |
| In Review → Inactive | VOID | 1 |
| Inactive → Active | ISSUED | 1 |
| null → Active | ISSUED | 1 |

Cause: upstream `STATUS_ORIGINAL` / normalization lagged current `PermitStatus` (e.g. still `issued` while DATA says FINALED), or treated administrative CLOSED as Final, or treated unissued APPROVED as Active.

After repair: Final 1,510; Active 246; Inactive 128; In Review 114; null 1 (empty PermitStatus shell with no dates).

### FILE_DATE

Ideal: populated for all records. **Already correct** where present — 0 mismatches vs ApplyDate; **0 FILLED/FIXED**. Remaining **4 missing** have blank `PermitAppliedDate` (two FINALED Oakland sewer-fee shells, two IN REVIEW shells). Not inventable from DATA.

Coverage after: 1,995 / 1,999 (99.8%).

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present and IssuedDate present, always matched IssuedDate (no incorrect overwrites).
- **40 FILLED** (6 from IssuedDate, 34 from ApprovedDate fallback) for Active / Final / Inactive.
- Remaining Active/Final gap: **7** (6 FINALED, 1 ISSUED) with neither IssuedDate nor ApprovedDate.

Coverage after repair: Active 245/246 (99.6%); Final 1,504/1,510 (99.6%); In Review 1/114; Inactive 52/128.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 21 Final rows missing FINAL_DATE; 1 Active row had FINAL_DATE equal to `PermitFinaledDate` while status still ISSUED.
- **16 FILLED** — all from `PermitFinaledDate` on rows whose status was corrected to Final (stale Active/In Review vs FINALED).
- **1 FIXED** — cleared the spurious Active FINAL_DATE.
- Remaining: **11 Final** (8 FINALED, 3 CO ISSUED) with blank FinaledDate and no usable final inspection.

Coverage after repair: Final 1,499/1,510 (99.3%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 53 | 4 → 1 |
| FILE_DATE | 0 | 0 | 4 → 4 |
| PERMIT_DATE | 40 | 0 | 237 → 197 |
| FINAL_DATE | 16 | 1 | 515 → 500 |

## Not repairable from DATA

- 4 blank application dates (FILE_DATE).
- 11 Final rows with no finaled/CO/final-inspection stamp (FINAL_DATE).
- 7 Active/Final rows with no IssuedDate/ApprovedDate (PERMIT_DATE).
- 1 empty-status shell with no dates (STATUS_NORMALIZED).
