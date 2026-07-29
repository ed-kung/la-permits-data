# San Bruno (CA) data repair

**Summary:** Assessed San Bruno's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_san_bruno.py`. San Bruno uses a civic portal payload (`permit_info` + `inspections`). The main defects are (1) 188 null `STATUS_NORMALIZED` values on `ADMIN.CLOSE` and legacy blank-`PermitStatus` shells, (2) Active/Final rows missing `PERMIT_DATE` when only `PermitApprovedDate` is present, and (3) `FINAL_DATE` entirely null because `PermitFinaledDate` is never populated — recoverable only from passed final inspections. The repair fills 186 statuses, 55 PERMIT_DATEs, and 693 FINAL_DATEs, and fixes 2 stale In Review→Active cases.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **San Bruno, CA**.

## DATA schema

All 2,000 rows have DATA with top-level keys including `permit_info`, `inspections`, `permit_no`, `address`, and parcel/lot metadata. Seven rows also carry `state` / `zip_code`. Canonical fields live under `permit_info`. Inferred content variants:

| Schema | N | Notes |
| --- | --- | --- |
| `permit_info_issued` | 947 | Issued present, no usable final insp |
| `permit_info_issued_final_insp` | 683 | Issued + passed final inspection |
| `permit_info_applied_only` | 175 | only Applied populated |
| `legacy_no_status` | 105 | blank PermitStatus with dates |
| `permit_info_approved_only` | 41 | Approved present, Issued blank |
| `permit_info_final_insp_only` | 24 | final insp present, Issued blank |
| `permit_info_empty_dates` | 18 | status present, no usable dates |
| `with_geo_permit_info_issued` | 7 | same as issued, plus state/zip |

Canonical mappings from DATA:

- `permit_info.PermitStatus` → `STATUS_NORMALIZED` (with IssuedDate override for pre-issuance labels)
- `permit_info.PermitAppliedDate` → `FILE_DATE`
- `permit_info.PermitIssuedDate` (fallback `PermitApprovedDate`) → `PERMIT_DATE`
- `permit_info.PermitFinaledDate` (always null in sample; fallback: latest passed final inspection via `Completed Date:`) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,447 / Inactive 187 / Active 103 / In Review 75 / missing 188.

Root cause: `STATUS_NORMALIZED` was derived from `STATUS_ORIGINAL`, which is blank for `ADMIN.CLOSE` (79) and for legacy shells with null `PermitStatus` (107, mostly 1997–2005). Two rows carry the unmapped label `OH_SNAP!`. Existing mapped statuses (`FINALED`, `ISSUED`, `EXPIRED`, `VOID`, `WITHDRAWN`, `ROUTED`, etc.) already matched `PermitStatus` correctly, except two pre-issuance labels that already had `PermitIssuedDate`.

Status map from `PermitStatus`:

| PermitStatus | → |
| --- | --- |
| FINALED, FINALED` | Final |
| ISSUED | Active |
| ROUTED, PLAN CHECK, SUBMITTED, READY TO ISSUE | In Review |
| EXPIRED, VOID, WITHDRAWN, ADMIN.CLOSE | Inactive |

Overrides:

1. Pre-issuance In Review labels that already carry `PermitIssuedDate` → Active (2 rows: `ROUTED`, `PLAN CHECK`).
2. Blank / unmapped `PermitStatus` inferred from dates → Active if Issued/Approved, else In Review if Applied only (`OH_SNAP!` → Active).

Repair performance: **186 FILLED, 2 FIXED**; missing after: **2** (empty `permit_info` shells `C0409-0019`, `E0205-0006`).

After: Final 1,447 / Inactive 266 / Active 206 / In Review 79 / missing 2.

Notable transitions: null→Inactive 79 (`ADMIN.CLOSE`); null→Active 101 (legacy blank status + `OH_SNAP!`); null→In Review 6 (applied-only blanks); In Review→Active 2.

### FILE_DATE

Before: 20 missing. Where both present, FILE_DATE matches `PermitAppliedDate` exactly (1,980/1,980).

The 20 gaps are mostly `VOID` shells and empty `permit_info` records with blank `PermitAppliedDate` (and usually blank Issued/Approved as well). No alternate application date exists in DATA.

Repair: **0 FILLED, 0 FIXED**. Coverage remains **1,980 / 2,000 (99.0%)**.

### PERMIT_DATE

Before: 265 missing. Where both present, PERMIT_DATE matches `PermitIssuedDate` exactly (1,735/1,735). Fifty-four Active/Final rows had `PermitApprovedDate` but null Issued/PERMIT; one additional fill came from status promotion context. Remaining Active/Final gaps have neither stamp.

Repair: **55 FILLED, 0 FIXED** — fills Issued (and Approved fallback) on Active/Final.

Remaining Active/Final gap: **64** (17 ISSUED Active + 47 FINALED with neither Issued nor Approved). After repair: Active **189 / 206 (91.7%)**; Final **1,400 / 1,447 (96.8%)**.

### FINAL_DATE

Before: **2,000 missing** (100%). `PermitFinaledDate` is null for every sample row — the agency never stamps a finaled date into `permit_info`. Completion evidence lives only in `inspections` (key `Completed Date:` on types like `**BUILDING FINAL`, `PLUMBING FINAL`, etc., with `result=PASS`).

Repair: **693 FILLED, 0 FIXED** from passed final inspections on Final rows.

Final coverage after repair: **693 / 1,447 (47.9%)**. Remaining 754 FINALED shells lack a usable final inspection (530 have no inspections at all; 151 have inspections but no FINAL-typed item; 73 have FINAL-typed items without a passed/completed date). No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_san_bruno.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 186 | 2 | 188 | 2 |
| FILE_DATE | 0 | 0 | 20 | 20 |
| PERMIT_DATE | 55 | 0 | 265 | 210 |
| FINAL_DATE | 693 | 0 | 2,000 | 1,307 |

### Coverage after repair

| Metric | Value |
| --- | --- |
| FILE_DATE populated | 1,980 / 2,000 (99.0%) |
| Active PERMIT_DATE | 189 / 206 (91.7%) |
| Final PERMIT_DATE | 1,400 / 1,447 (96.8%) |
| Final FINAL_DATE | 693 / 1,447 (47.9%) |
| Spurious FINAL on non-Final | 0 |

### Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_san_bruno.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_san_bruno_repaired.parquet`
