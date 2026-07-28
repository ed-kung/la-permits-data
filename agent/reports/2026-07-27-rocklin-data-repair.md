# Rocklin (CA) data repair

**Summary:** Rocklin was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows use one portal schema (`permit_info` + `search_data`). Status was mostly already correct; the main fixes were blank PRE* statuses, one mis-mapped `APPROVED W/COND`, and nine stale ISSUED/PENDING rows that already had `PermitFinaledDate`. `PERMIT_DATE` gaps on Active/Final were largely fillable from `PermitApprovedDate` when Issued was empty. `FILE_DATE` and most remaining Final `FINAL_DATE` gaps cannot be filled from DATA.

## Jurisdiction selection

Went down first-seen `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`. Existing scripts live under `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing pair: **Rocklin, CA** (`agent/scripts/ca/data_repair_ca_rocklin.py`).

## DATA schema

All 2,000 rows share top-level keys:
`contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`.

Canonical sources in `permit_info`:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `PermitStatus` (+ date inference when blank / stale) |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate`, else finaling inspection `Completed` |

`INFERRED_SCHEMA` is `permit_info_search_data` for every row.

## Field assessment

### STATUS_NORMALIZED

Pre-repair: Final 1,141 / Active 450 / In Review 286 / Inactive 116 / missing 7.

`STATUS_ORIGINAL` matches `PermitStatus` (lowercased) on every row. Mapping was generally correct (`FINALED`→Final, `ISSUED`/`APPROVED`→Active, `PENDING`/`APPLIED`→In Review, `VOID`/`EXPIRED`/`WITHDRAWN`/`INACTIVE`→Inactive).

Issues found:

1. **7 blank `PermitStatus`** (all `PRE*` permit requests) with applied date only → missing status; fillable as **In Review**.
2. **`APPROVED W/COND` (1)** incorrectly labeled In Review → should be **Active**.
3. **9 rows with `PermitFinaledDate` but non-Final status** (7 `ISSUED`, 2 `PENDING`) → status should be **Final**. One `VOID` with a finaled stamp stays **Inactive** (void is authoritative).

### FILE_DATE

22 missing; all also have empty `PermitAppliedDate` / `APPLIED` (21 VOID, 1 PENDING). No alternate application date in DATA. When present, `FILE_DATE` always equals `PermitAppliedDate` (0 mismatches). Coverage after repair: **98.9%** (1,978 / 2,000).

### PERMIT_DATE

When present, always equals `PermitIssuedDate` (0 mismatches). Ideal: populate for Active and Final.

Gaps before repair: 57 Active, 19 Final missing. Of those, **50 Active + 9 Final** had `PermitApprovedDate` but empty Issued — fillable. Remaining unfillable: mostly APPROVED encroachment / COMPLETED police-fee shells with neither Issued nor Approved.

### FINAL_DATE

When present, always equals `PermitFinaledDate`. Ideal: populate for Final only.

12 Final rows missing `FINAL_DATE` with empty Finaled and no usable finaling inspections (9 COMPLETED PDOP/fee, 2 CLOSED legacy, 1 FINALED SFR). Not fillable from DATA.

10 non-Final rows carried a `FINAL_DATE`; 9 of those are the stale ISSUED/PENDING cases upgraded to Final (date kept); the VOID case is cleared.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_rocklin.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 7 | 10 | 7 | 0 |
| FILE_DATE | 0 | 0 | 22 | 22 |
| PERMIT_DATE | 60 | 0 | 442 | 382 |
| FINAL_DATE | 0 | 1 | 861 | 862 |

Status after repair: Final 1,150 / Active 444 / In Review 290 / Inactive 116 (no nulls).

Coverage after repair:

- FILE_DATE: 1,978 / 2,000 (98.9%)
- PERMIT_DATE: Active 437/444 (98.4%); Final 1,140/1,150 (99.1%)
- FINAL_DATE: Final 1,138/1,150 (99.0%); 0 on non-Final

## Remaining gaps (not repairable from DATA)

- **FILE_DATE (22):** empty applied fields, mostly VOID shells.
- **PERMIT_DATE:** 7 Active (6 APPROVED, 1 ISSUED) and 10 Final (5 COMPLETED, 5 FINALED) with neither Issued nor Approved.
- **FINAL_DATE:** 12 Final rows (9 COMPLETED, 2 CLOSED, 1 FINALED) with no Finaled date and no finaling inspection Completed date.
