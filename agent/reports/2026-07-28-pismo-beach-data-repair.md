# Pismo Beach (CA) data repair

**Summary:** Pismo Beach was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script (La Cañada Flintridge already has `data_repair_ca_la_canada_flintridge.py` under an accent-normalized slug). DATA is a flat tabular export with Status / Issue Date only — no apply or finaling timestamps. Upstream left 578 statuses null (Admin Approval, Construction Permit, PC/CC Approval, plus column-shifted rows) and mis-mapped Estimate→Final and Revision Approved→In Review. Repair fills/fixes 467 statuses (160 unrecoverable shifted/description shells left null). FILE_DATE and FINAL_DATE remain fully missing. PERMIT_DATE fills 5 Active/Final rows from date-like Status on shifted Closed/Issued rows; 322 Active/Final rows still lack a parseable issuance stamp because Issue Date often holds Work Description text.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order (accent-normalized city slugs). The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Pismo Beach, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Flat open-data keys: `Status`, `Address `, `Permit #`, `Permit Type`, `Sub Type`, optional `Issue Date`, optional `Work Description`.

| Schema | n | Description |
| --- | ---: | --- |
| `tabular_spaced` | 1,388 | `Address ` / `Permit #` + Issue Date + Work Description |
| `tabular_spaced_no_wd` | 438 | Spaced headers; Issue Date present, no WD |
| `tabular_shifted` | 161 | Status not a lifecycle label (often a date); real status sometimes in `Sub Type` |
| `tabular_spaced_no_issue` | 13 | Spaced; no Issue Date key |

Canonical fields: `Status` (fallback `Sub Type` on shifted rows, excluding subtype category `Other`) → STATUS_NORMALIZED; `Issue Date` (fallback date-like `Status` / `Sub Type`) → PERMIT_DATE. No FILE_DATE or FINAL_DATE source.

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,110 / missing 578 / Inactive 114 / In Review 114 / Active 84.

Status map from DATA:

| DATA Status | → |
| --- | --- |
| Closed, Finaled | Final |
| Issued, Admin Approval, Construction Permit, PC Approval, CC Approval | Active |
| Revision Approved | Active if issuance stamp present, else In Review |
| Under Review, Online Application Received, Application, Pending, Estimate | In Review |
| Expired, Withdrawn, Void, Denied, Other | Inactive |

Main errors vs DATA:

- **Null statuses fillable (413):** Admin Approval (231), Construction Permit (139), PC Approval (42), CC Approval (1) → FILLED Active.
- **Shifted Closed/Issued (5):** date-as-Status with Sub Type Closed (4) or Issued (1) → FILLED Final/Active.
- **Revision Approved still In Review (46):** approval with parseable Issue Date → FIXED to Active. Five Revision Approved shells without an issuance stamp stay In Review.
- **Estimate → Final (3):** `STATUS_ORIGINAL=estimate` incorrectly mapped to Final (no Issue Date) → FIXED to In Review.
- **Unrecoverable (160):** mostly Eng Migrated rows with date-as-Status and Sub Type `Eng Migrated` (143); also Planning/Other date-shifted (5), Home Occupation (3), Temporary Outdoor Dining (2), and a few description-as-Status / null-Status shells. Sub Type `Other` is a planning subtype, not the Inactive `Status=Other` label, so it is not used as a status fallback.

### FILE_DATE

Missing on 2,000 / 2,000. DATA has no application / submittal / created date. `Issue Date` is issuance, not filing — not used as FILE_DATE. **0** fills/fixes.

### PERMIT_DATE

Missing on 600 / 2,000 before repair. When both present, existing PERMIT_DATE always matched parseable `Issue Date` (1,400 calendar-day matches; 0 mismatches). ~586 Issue Date values are work-description text (column shift; WD key often absent).

Fillable after status repair (shifted Active/Final rows where Status holds `MM/DD/YYYY` and Issue Date is text):

- Closed Daily Transportation rows with Status dates `04/29/2011` (3) and `04/23/2018` (1)
- Issued No Fee Encroachment row with Status date `01/27/2015` (1)

→ **5 FILLED**. Remaining Active/Final gaps (322): Closed shells with text Issue Date (315), Admin Approval without date (4), Finaled Revision Permits with text Issue Date (2), Issued Stormwater with text Issue Date (1).

### FINAL_DATE

Missing on 2,000 / 2,000. Closed / Finaled map to Final, but DATA has no completion / finaled / signoff timestamp. **0** fills/fixes.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_pismo_beach.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_pismo_beach_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 418 | 49 | 578 → 160 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 5 | 0 | 600 → 595 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Status transitions: `__NA__`→Active 413; In Review→Active 46; Final→In Review 3; `__NA__`→Final 4; `__NA__`→Active (shifted Issued) 1.

After repair, PERMIT_DATE coverage: Active 539/544 (99.1%); Final 794/1,111 (71.5%). FILE_DATE and FINAL_DATE remain 0% for all statuses — structural DATA limitation, not a mapping bug.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_pismo_beach.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_pismo_beach_repaired.parquet`
