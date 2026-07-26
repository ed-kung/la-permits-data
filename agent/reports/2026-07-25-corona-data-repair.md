# Corona (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Corona — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Across 2,000 sample rows of a single `permit_info` portal schema, 172 status labels were corrected (mostly Active→Final where `PermitFinaledDate` was already present; plus 3 false Finals on SEND NOTICE TO CIP), `FILE_DATE` was already correct wherever DATA provides an applied date (1 unfillable gap), `PERMIT_DATE` gained 192 fills from `PermitApprovedDate` when Issued was empty, and `FINAL_DATE` gained 6 fills from final / C of O inspections while 2 spurious finals on EXPIRED rows were cleared. Large residual gaps remain on 1990–1997 legacy `FINAL` rows that lack finaled dates and inspections.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Corona, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_corona.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/corona_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

All rows share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Content variants:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_basic` | 1,235 | Empty `inspections` list |
| `permit_info_full` | 765 | Non-empty `inspections` |

Canonical fields live in `permit_info`: `PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate`, `PermitApprovedDate`, `PermitFinaledDate`.

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 974 · Active 781 · In Review 152 · Inactive 93 · missing 0

Existing maps from `STATUS_ORIGINAL` / `PermitStatus` were consistent for most labels (`FINALED`/`FINAL`/`C OF O`→Final, `ISSUED`/`APPROVED`/`ACTIVE`→Active, plan-check / applied / pending→In Review, void / withdrawn / expired→Inactive). Issues:

1. **169 rows** still carried `PermitFinaledDate` but were labeled Active (131 APPROVED, 35 ISSUED) or In Review (2 NIC, 1 PENDING). Portal status lagged the finaled date → **FIXED to Final**.
2. **3 SEND NOTICE TO CIP** rows were labeled Final with no Issued, Approved, or Finaled dates (public-works notice workflow) → **FIXED to In Review**.
3. **2 EXPIRED** rows carry `PermitFinaledDate` but stay **Inactive** (treated as close/void timestamps, same convention as Fontana).

**After:** Final 1,140 · Active 615 · In Review 152 · Inactive 93 · missing 0  
Flags: **FILLED 0 · FIXED 172**

### FILE_DATE

**Before:** 1 missing (99.95% populated).

- Existing `FILE_DATE` matches `PermitAppliedDate` on all 1,999 rows where Applied is present (0 mismatches).
- The 1 gap has empty `PermitAppliedDate` and no alternate application date in `search_data` → not fillable.

Flags: **FILLED 0 · FIXED 0** · missing 1 → 1

### PERMIT_DATE

**Before:** 708 missing. When present, `PERMIT_DATE` already equals `PermitIssuedDate` (1,292/1,292; 0 mismatches vs Issued/Approved).

Issues:
1. **192 Active/Final** rows had empty Issued but populated `PermitApprovedDate` (mostly APPROVED status) → **FILLED** from Approved.
2. Remaining Active/Final gaps (~289 pre-repair among Active/Final; ~287 after, concentrated in utility/overload/meter permits with status ISSUED/ACTIVE) have neither Issued nor Approved in DATA → not fillable.

**After:** missing 516. Active 355/615 (57.7%) · Final 1,113/1,140 (97.6%).  
Flags: **FILLED 192 · FIXED 0**

### FINAL_DATE

**Before:** 1,247 missing; Final 582/974 (59.8%) populated. When present, `FINAL_DATE` already equals `PermitFinaledDate` (753/753). Also, 166 Active and 3 In Review rows already had `FINAL_DATE` matching Finaled — those were status errors (see above), not date errors.

Issues:
1. After status remaps, Finaled dates on the 169 upgraded rows become valid Final finals (no date flag; status was FIXED).
2. **6 Final** rows with empty Finaled but a passed final / C of O inspection (`Type`/`Result`/`Completed`) → **FILLED**.
3. **2 Inactive EXPIRED** rows with Finaled close timestamps → **FIXED** (cleared).
4. **~383 Final** still lack Finaled and a usable finaling inspection — almost all are legacy `PermitStatus=FINAL` (1990–1997; n=369) with Issued/Approved dates but blank Finaled and empty inspections. Also 11 `C OF O` / 3 complete-like rows without a passed final inspection.

**After:** Final 757/1,140 (66.4%) have `FINAL_DATE`; Active / In Review / Inactive have 0.  
Flags: **FILLED 6 · FIXED 2** · missing 1,247 → 1,243

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 172 | 0 → 0 |
| FILE_DATE | 0 | 0 | 1 → 1 |
| PERMIT_DATE | 192 | 0 | 708 → 516 |
| FINAL_DATE | 6 | 2 | 1,247 → 1,243 |

## Not repairable from DATA

- 1 blank `PermitAppliedDate` (no FILE_DATE source).
- Legacy `FINAL` cohort (~369) without Finaled dates or inspections.
- Many Active ISSUED/ACTIVE utility, daily overload, garage-sale, and meter permits with neither Issued nor Approved dates.
- EXPIRED rows with Finaled timestamps intentionally left Inactive (FINAL_DATE cleared).
