# Oxnard (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Oxnard — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Across 2,000 sample rows and three DATA schemas, all 709 missing statuses were filled and 3 status mismatches fixed; `FILE_DATE` was already correct wherever DATA provides an application date (306 project rows remain unfillable); `PERMIT_DATE` was corrected on 725 rows because legacy `Permit Date` is often a finaling stamp rather than issuance (`Issue Date` is canonical); and every Final row now has a `FINAL_DATE` while the FINAL-before-PERMIT anomaly dropped from 435 to 3. After repair: Final has 100% `PERMIT_DATE` and 100% `FINAL_DATE`; Active has 95% `PERMIT_DATE` (remaining gaps are detail_only stubs with no issuance fields).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Oxnard, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_oxnard.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/oxnard_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `permit_status` | 1,025 | Legacy portal: `detail`, `permit_status_detail`, `insp_status_detail` |
| `detail_only` | 669 | Sparse stub: `detail` + fees only (mostly records reports / receipts) |
| `project` | 306 | Newer workflow: `project` + `description` plan-check / issuance tracking |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 659 · Active 561 · In Review 63 · Inactive 8 · missing 709

Issues:
1. **669 `detail_only` rows** had null status. `Application Status` is `CLOSED` (573), `IN PLAN CHECK` (66), or `APPROVED` (30). These are administrative stubs (e.g. report of building records, receipt system), not full permit records → mapped **Inactive** / **In Review** / **Active** (same convention as Thousand Oaks `detail_only`).
2. **40 `project` rows** had null status. Derived from Permit Center Tracking `Type` (and other `description` Types): Approved / Notified → **Active**; corrections / hold / routed → **In Review**; withdrawn / expired / rejected → **Inactive**.
3. **3 `permit_status` rows** where `Status for Permit Number` = `PERMIT PRINTED` disagreed with `STATUS_ORIGINAL` / `STATUS_NORMALIZED` (2 labeled In Review, 1 Final) → **FIXED** to **Active**.

`permit_status` status is otherwise already correctly mapped from `Status for Permit Number` (`CLOSED` / `FINAL INSPECTION COMPLETE` / `C.O. ISSUED`→Final, `PERMIT PRINTED`→Active, `PLAN CHECK` / `TO BE ISSUED`→In Review, `PERMIT REVOKED`→Inactive).

**After:** Final 658 · Active 612 · Inactive 586 · In Review 144 · missing 0  
Flags: **FILLED 709 · FIXED 3**

### FILE_DATE

**Before:** 306 missing (all `project` rows).

- `permit_status` / `detail_only`: already populated for all rows and matches `Application Date` at calendar-day resolution. No fills or fixes.
- `project`: DATA has no application / submittal date (only `Last Action` timestamps on workflow steps). **Not repairable.**

**After:** still 306 missing (all `project`).  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 709 missing. Active and Final `permit_status` rows already had values, but many were wrong.

Primary bug in `permit_status`: existing `PERMIT_DATE` was taken from **`Permit Date`**, which for Final rows (and some Active) is a **finaling / last-activity stamp**, not issuance. True issuance is **`Issue Date`** (always ≤ Permit Date when both exist). Using Permit Date as issuance produced 435 Final rows with `FINAL_DATE` < `PERMIT_DATE`.

Repairs:
- Overwrite with `Issue Date` for Active/Final when present (**656 date corrections**: 642 Final + 14 Active).
- Clear spurious `PERMIT_DATE` on 61 In Review + 8 Inactive rows with no `Issue Date`.
- Fill 18 `project` Active rows missing `PERMIT_DATE` from PCT / Approved `Last Action` (existing project dates left as-is; they already match a workflow Last Action).

**After:** missing 760 (In Review 144 + Inactive 586 + 30 Active `detail_only` stubs). Active 582/612 · Final 658/658.  
Flags: **FILLED 18 · FIXED 725**

`FINAL_DATE` < `PERMIT_DATE` among Final rows: **435 → 3**.

### FINAL_DATE

**Before:** 1,376 missing; 35 Final rows lacked `FINAL_DATE`; 1 non-Final row carried a final date (the status-mismatch case later remapped to Active).

Repairs:
- For `permit_status` Final rows: latest inspection whose name contains `FINAL` and status starts with `APPROVED` (includes `APPROVED WITH EXCEPTION`); else last approved inspection; else `Permit Date` as legacy finaling proxy → **FILLED 35** (all remaining Final gaps closed).
- Fix 21 Final rows where the stored date differed from the preferred inspection / Permit Date value.
- Clear `FINAL_DATE` on the 1 row remapped Active→non-Final (plus any other non-Final clears counted in FIXED).

**After:** Final 658/658 have `FINAL_DATE`; Active / In Review / Inactive have 0.  
Flags: **FILLED 35 · FIXED 22**

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 709 | 3 | 709 → 0 |
| FILE_DATE | 0 | 0 | 306 → 306 |
| PERMIT_DATE | 18 | 725 | 709 → 760 |
| FINAL_DATE | 35 | 22 | 1,376 → 1,342 |

Ideal coverage after repair:
- `FILE_DATE`: 100% of `permit_status` + `detail_only`; 0% of `project` (no source field)
- `PERMIT_DATE`: 100% of Final; 95% of Active (30 `detail_only` APPROVED stubs lack issuance)
- `FINAL_DATE`: 100% of Final

Missing-count increases for `PERMIT_DATE` reflect intentional clears of incorrect values on In Review / Inactive rows, not loss of recoverable issuance data.

## Not repairable

- All 306 `project` rows lack an application date in DATA → `FILE_DATE` remains null.
- `detail_only` stubs have no Issue Date or inspections → `PERMIT_DATE` / `FINAL_DATE` remain null (status is Active / In Review / Inactive after fill; none are Final).
- `project` rows have no finaling signal → none classified Final; `FINAL_DATE` stays null.
- 16 Final `permit_status` rows lack `Issue Date` → `PERMIT_DATE` left as the existing `Permit Date` value (cannot confirm true issuance).
- 3 Final rows still have `FINAL_DATE` < `PERMIT_DATE` after using Issue Date (inspection / issue ordering quirks in source).
