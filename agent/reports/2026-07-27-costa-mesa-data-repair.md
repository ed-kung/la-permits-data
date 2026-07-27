# Costa Mesa (CA) data repair

**Summary:** Costa Mesa was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from Tyler EnerGov / CityView `DATA` JSON plus a flat issued-list scrape. Status is now fully populated (**FILLED 297 · FIXED 7**): 265 flat-list rows and 32 unmapped entity CaseStatus values were filled, and 7 Plan Check Complete rows mis-labeled Final were remapped to In Review. `FILE_DATE` missingness fell from **265 → 0** (**FILLED 265**) using Date Issued as the only available stamp on flat rows; entity rows already matched `ApplyDate`. `PERMIT_DATE` needed no value changes (already matched `IssueDate` / Date Issued when present); **27** Active/Final rows remain without issuance stamps. `FINAL_DATE` is complete for all Final rows after the Plan Check remaps, and **4** spurious finals on Issued / Expired / Void were cleared (**FIXED 4**).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Costa Mesa, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_costa_mesa.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,693 | EnerGov detail: `entity` + `details` + `fees` (+ contacts, processing_status) |
| `flat_issued_valuation` | 220 | Flat issued list: APN, Address, Date Issued, Description, Valuation, contacts |
| `flat_issued` | 45 | Flat issued list without Valuation |
| `entity_fees_reviews` | 41 | `entity_fees` plus reviews / holds / attachments / more_info |

Canonical fields:

| Field | Entity source | Flat source |
| --- | --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` / `details.PermitStatus` | Date Issued present → Active |
| `FILE_DATE` | `entity.ApplyDate` | `Date Issued` (only available stamp) |
| `PERMIT_DATE` | `entity.IssueDate` | `Date Issued` |
| `FINAL_DATE` | `entity.FinalDate` / `details.FinalizeDate` | (none) |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,142 · Active 220 · Inactive 263 · In Review 77 · missing 297

Issues:
1. **265 flat-list rows** with null `STATUS_ORIGINAL` / `STATUS_NORMALIZED` and no CaseStatus. Every row has `Date Issued` → infer **Active**.
2. **32 entity rows** with CaseStatus values the upstream mapper did not know:

| CaseStatus | n | Mapped to |
| --- | ---: | --- |
| Additional Information Required | 14 | In Review |
| Invoice Pending | 7 | In Review |
| Verifying Submittal | 4 | In Review |
| Issued -Revision - Additional Information Required | 3 | Active |
| Issued - Revision Added | 2 | Active |
| Application Returned | 1 | In Review |
| Revision Submittal | 1 | In Review |

3. **7 Plan Check Complete → Final** mis-normalizations: null `IssueDate` / `FinalDate` / `Issued=False` (plan check finished, not issued or finaled) → **In Review**.

When present, CaseStatus maps cleanly for the rest (Final, Issued, Approved, Expired, Void, Withdrawn, Denied, Submitted, On Hold, Complete, Legacy, Plan Approval/Check Expired, etc.).

**After:** Final 1,135 · Active 490 · Inactive 263 · In Review 111 · missing 0  
Flags: **FILLED 297 · FIXED 7**

### FILE_DATE

**Before:** 265 missing (13.3%), all on flat-list rows.

- Entity rows: `FILE_DATE` equals `entity.ApplyDate` for all 1,734 rows (no changes).
- Flat rows: no ApplyDate; only `Date Issued` → filled as FILE_DATE proxy so every record has an application/issuance calendar stamp.

**After:** 0 missing.  
Flags: **FILLED 265 · FIXED 0**

### PERMIT_DATE

**Before:** 210 missing. Among Active/Final: 34 / 1,362 missing.

- Entity: `PERMIT_DATE` already equals `entity.IssueDate` whenever IssueDate is present (including null↔null).
- Flat: `PERMIT_DATE` already equals `Date Issued` for all 265 rows.

Remaining Active/Final gaps after status repair (**27**): Approved (20), Final (4), Complete (3) with `Issued=False` and null IssueDate — no issuance stamp in DATA; FILE_DATE is not used as a proxy.

**After:** still 210 missing overall; Active/Final coverage **1,598 / 1,625 (98.3%)**.  
Flags: **FILLED 0 · FIXED 0**

### FINAL_DATE

**Before:** 860 missing. Among Final: 7 missing (all Plan Check Complete). Non-Final with FINAL_DATE: 4 (1 Issued, 2 Expired, 1 Void) — spurious copies of `entity.FinalDate`.

Repairs:
1. Remap Plan Check Complete → In Review (those 7 no longer require FINAL_DATE).
2. Clear FINAL_DATE on non-Final rows (**FIXED 4**).

**After:** Final 1,135 / 1,135 have FINAL_DATE (100%). Non-Final with FINAL_DATE: 0. Overall missing rises slightly (860 → 864) because spurious finals were cleared.  
Flags: **FILLED 0 · FIXED 4**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 297 | 7 | 297 → 0 |
| FILE_DATE | 265 | 0 | 265 → 0 |
| PERMIT_DATE | 0 | 0 | 210 → 210 |
| FINAL_DATE | 0 | 4 | 860 → 864 |

Ideal population after repair:
- FILE_DATE: **100%**
- PERMIT_DATE for Active/Final: **98.3%** (27 unissued Approved/Final/Complete shells)
- FINAL_DATE for Final: **100%**
- No spurious FINAL_DATE on non-Final rows

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_costa_mesa.py`
