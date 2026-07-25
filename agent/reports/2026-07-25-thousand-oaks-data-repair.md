# Thousand Oaks (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Thousand Oaks — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Across 2,001 sample rows and three DATA schemas, status gaps were fully closed (37 filled, 3 fixed), `FILE_DATE` needed no changes, `PERMIT_DATE` was corrected on 585 rows (legacy “Permit Date” was often a finaling date), and `FINAL_DATE` was filled/fixed so every Final record has a completion date while spurious finals on non-Final rows were cleared. After repair: Active/Final have 100% `PERMIT_DATE`, Final has 100% `FINAL_DATE`, and all rows have `FILE_DATE`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Thousand Oaks, CA** (n=2,001)
- Script: `agent/scripts/data_repair_ca_thousand_oaks.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/thousand_oaks_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `entity_full` | 1,261 | Tyler EnerGov-style: `entity`, `details`, fees/contacts/reviews/holds |
| `permit_status` | 726 | Legacy portal: `detail`, `permit_status_detail`, `insp_status_detail` |
| `detail_only` | 14 | Sparse stub: `detail` only (no permit/inspection blocks) |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,533 · Inactive 235 · Active 168 · In Review 28 · missing 37

Issues:
1. **23 `entity_full` rows** with `CaseStatus` / `PermitStatus` = `Permit Approval Expired` had null `STATUS_NORMALIZED` (unmapped original status) → should be **Inactive**.
2. **14 `detail_only` rows** had null status; `Application Status` is `IN PLAN CHECK` (13) or `CLOSED` (1) → **In Review** / **Inactive**.
3. **3 `entity_full` rows** had stale `CaseStatus=Issued` while `details.PermitStatus=Finaled` and `FinalizeDate` present; labeled Active → should be **Final**.

`permit_status` rows were already correctly mapped from `Status for Permit Number` (`FINAL INSPECTION COMPLETE`→Final, `PERMIT PRINTED`→Active, `PLAN CHECK`/`TO BE ISSUED`→In Review, `PERMIT REVOKED`→Inactive).

**After:** Final 1,536 · Inactive 259 · Active 165 · In Review 41 · missing 0  
Flags: **FILLED 37 · FIXED 3**

### FILE_DATE

Already populated for all 2,001 rows and matches `entity.ApplyDate` / `Application Date` at calendar-day resolution. No fills or fixes.

Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 64 missing (mostly Inactive / In Review — acceptable). Active and Final already had values, but many were wrong.

Primary bug in `permit_status`: existing `PERMIT_DATE` was taken from **`Permit Date`**, which for Final rows (and 6 Active rows) is a **finaling / last-activity stamp**, not issuance. True issuance is **`Issue Date`** (always ≤ Permit Date when both exist).

Repairs:
- Overwrite with `Issue Date` for Active/Final/Inactive when present (**561 date corrections**, including all 555 Final `permit_status` rows).
- Clear spurious `PERMIT_DATE` on 23 In Review rows with no `Issue Date`.

`entity_full` issuance already matched `IssueDate`; no date corrections there beyond status-driven Final remaps.

**After:** missing 87 (In Review 41 + unissued Inactive). Active 165/165 · Final 1,536/1,536.  
Flags: **FILLED 0 · FIXED 585**

### FINAL_DATE

**Before:** 368 missing; 5 Final rows lacked `FINAL_DATE`; 105 non-Final `entity_full` rows carried a `FinalDate` (often equal to `IssueDate`).

Repairs:
- Prefer `details.PermitStatus` over `CaseStatus`; for the 3 Issued→Finaled remaps, **FILL** from `details.FinalizeDate`.
- For `permit_status` Final rows: latest inspection whose name contains `FINAL` and status starts with `APPROVED` (includes `APPROVED WITH EXCEPTION`); else last approved inspection; else `Permit Date`.
- Clear `FINAL_DATE` on non-Final rows (105 `entity_full` clears).
- Fix 6 Final rows where the stored date was earlier than the latest approved final/last inspection.

**After:** Final 1,536/1,536 have `FINAL_DATE`; Active / In Review / Inactive have 0.  
Flags: **FILLED 8 · FIXED 111**

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 37 | 3 | 37 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 585 | 64 → 87 |
| FINAL_DATE | 8 | 111 | 368 → 465 |

Ideal coverage after repair:
- `FILE_DATE`: 100% of all rows
- `PERMIT_DATE`: 100% of Active and Final
- `FINAL_DATE`: 100% of Final

Missing-count increases for dates reflect intentional clears of incorrect values on In Review / non-Final rows, not loss of recoverable data.

## Not repairable

- `detail_only` stubs have no issuance or inspection fields → `PERMIT_DATE` / `FINAL_DATE` remain null (status is In Review or Inactive after fill).
- Unissued Inactive / In Review `entity_full` rows correctly lack `IssueDate` / `FinalDate`.
