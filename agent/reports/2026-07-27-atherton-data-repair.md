# Atherton (CA) data repair

**Summary:** Atherton was the first `(JURISDICTION, STATE)` pair without an existing repair script (alphabetically after Atascadero). Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the civic-portal `DATA` JSON (`permit_info` / `search_data` / list-of-list `inspections`). Status missingness fell **101 → 24** (**FILLED 77 · FIXED 23**): blank-`PermitStatus` CONVERTED shells with Issued → Active, and `APPROVED-STAFF` remapped In Review → Active. `FILE_DATE` already matched `PermitAppliedDate` wherever Applied exists (**FILLED/FIXED 0**); 326 rows lack Applied. `PERMIT_DATE` missingness fell **199 → 178** (**FILLED 21**) via Approved when Issued blank for Active/Final. `FINAL_DATE` gained **FILLED 6** from passed FINAL inspections when `PermitFinaledDate` was blank; 151 Final rows still lack any final source.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Atherton, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_atherton.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/atherton_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Sub-schemas reflect which `permit_info` fields are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,246 | Issued + Finaled present |
| `permit_info_issued` | 478 | Issued present, Finaled blank |
| `permit_info_applied_only` | 133 | Only Applied populated |
| `legacy_no_status` | 77 | Blank `PermitStatus` but dates present |
| `permit_info_empty_dates` | 37 | Status/desc text, no usable dates |
| `permit_info_approved_only` | 19 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 10 | Finaled present, Issued blank |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (prefer Final when non-inactive and `PermitFinaledDate` present; blank status inferred from dates) |
| `FILE_DATE` | `PermitAppliedDate`; else `search_data.APPLIED` |
| `PERMIT_DATE` | `PermitIssuedDate`; else `search_data.ISSUED`; else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest passed FINAL inspection date |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,413 · Active 186 · In Review 153 · Inactive 147 · missing 101

`PermitStatus` and `STATUS_ORIGINAL` agree (case-normalized) whenever either is set. Two repairable problem classes:

1. **Blank status (101 rows).** All `PermitType=CONVERTED` historic shells with empty `PermitStatus`. Of these, 77 have an Issued date (and already carried `PERMIT_DATE`); 24 have no dates at all.
2. **`APPROVED-STAFF` → In Review (23 rows).** Upstream left these as In Review; 16 already have Issued and all but one have Approved. Treated as Active (consistent with `APPROVED` → Active and `APPROV*` fuzzy rule used elsewhere).

Letter codes (`F`→Final, `A`/`I`→In Review, `X`/`V`/`E`/`C`→Inactive, `S`→Active) and verbose labels (`FINALED`, `ISSUED`, `IN QUEUE`, `UNDER REVIEW`, `EXPIRED*`, `VOID`, `WITHDRAWN`, `DENIED-STAFF`, `HISTORIC RECORD`, `ARCHIVE`) already matched the intended normalization when status was present. No rows had a `PermitFinaledDate` while labeled non-Final.

| Change | n | Reason |
| --- | ---: | --- |
| null → Active | 77 | Blank status + Issued date |
| In Review → Active | 23 | `APPROVED-STAFF` |

**After:** Final 1,413 · Active 286 · Inactive 147 · In Review 130 · missing 24  
Flags: **FILLED 77 · FIXED 23**

Not repairable: 24 empty-date CONVERTED shells with no status or dates in DATA.

### FILE_DATE

**Before:** 326 missing (16.3%).

- Where present (1,674), `FILE_DATE` always equals `PermitAppliedDate` (day match). `search_data.APPLIED` does not add any additional fillable rows.
- All 326 missing rows also lack Applied in both `permit_info` and `search_data` (mostly legacy `F` / blank-status CONVERTED records that only have Issued, and sometimes Finaled).

Do not backfill application date from Issued — that would conflate filing with issuance.

**After:** still 326 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 199 missing (9.9%). Among Active/Final: 10 / 19 missing.

Root cause: upstream left `PERMIT_DATE` null when `PermitIssuedDate` was blank even if `PermitApprovedDate` was available. Wherever Issued was present, `PERMIT_DATE` already matched it (0 mismatches / 1,801).

Repairs (Active / Final only after status repair):
1. Prefer `PermitIssuedDate` / `search_data.ISSUED`.
2. Else `PermitApprovedDate`.

| Change | n |
| --- | ---: |
| null → Approved (Active, incl. remapped APPROVED-STAFF) | 14 |
| null → Approved (Final) | 7 |

**After:** 178 missing. Active 283/286 (99.0%); Final 1,401/1,413 (99.2%).  
Flags: **FILLED 21 · FIXED 0**

Not repairable: Active/Final rows with neither Issued nor Approved (mostly legacy Final shells and a few ISSUED tree permits with blank Issued/Approved).

### FINAL_DATE

**Before:** 744 missing. Final coverage 1,256/1,413 (88.9%). No spurious finals on non-Final rows. Where present, `FINAL_DATE` always matched `PermitFinaledDate`.

Root cause for Final gaps: status codes `F` / `FINALED` / `FINAL` / `HISTORIC RECORD` / `ARCHIVE` without a populated `PermitFinaledDate` (157 rows, mostly CONVERTED). Six of those have a passed FINAL inspection with a usable date in the list-of-list `inspections` payload.

**After:** 738 missing. Final 1,262/1,413 (89.3%); Active/In Review/Inactive all 0%.  
Flags: **FILLED 6 · FIXED 0**

Not repairable: 151 Final rows with neither `PermitFinaledDate` nor a usable FINAL inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 77 | 23 | 101 → 24 |
| `FILE_DATE` | 0 | 0 | 326 → 326 |
| `PERMIT_DATE` | 21 | 0 | 199 → 178 |
| `FINAL_DATE` | 6 | 0 | 744 → 738 |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_atherton.py`
- Repaired sample: `AGENT_DATA_PATH/atherton_repaired_sample.parquet`
