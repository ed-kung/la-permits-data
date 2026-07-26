# Eureka (CA) data repair

**Summary:** Eureka was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` using the OpenGov-style `DATA` JSON (`main` / `extra` / `location`). Status is now fully populated (**FILLED 53 · FIXED 1**): null `main.status` rows were filled from legacy/OpenGov status strings, and one row with `STATUS_ORIGINAL=active` but `main.status=2` was corrected to Final. `FILE_DATE` was already complete but used `dateCreated`; **24 rows** were FIXED to the later `dateSubmitted` calendar day. `PERMIT_DATE` and `FINAL_DATE` were universally missing; the repair filled **1,391** issue dates and **878** final dates from `ISSUED`/`FINALED` and legacy numeric field IDs (rejecting sentinel stamps such as `1950-01-01` and bulk `2022-02-22` / `2022-09-01` migration dates). Remaining gaps are concentrated in modern `form_extra` records that lack issuance/finaling timestamps.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Eureka, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_eureka.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/eureka_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `main`, `extra`, `location`. Sub-schemas are distinguished by `extra` field layout:

| Schema | n | Description |
| --- | ---: | --- |
| `building_legacy` | 666 | Numeric keys ~23692–23888 (Legacy Building Permit) |
| `form_extra` | 381 | Modern form fields; few usable permit dates |
| `named_extra` | 333 | String keys `STATUS`, `APPLIED`, `ISSUED`, `FINALED`, … |
| `code_enforcement_legacy` | 178 | Keys ~25090–25107 |
| `encroachment_legacy` | 115 | Keys ~23475–23507 |
| `public_works_legacy` | 104 | Keys ~36881–36898 |
| `design_review_legacy` | 77 | Keys ~25718–25745 |
| `home_occupation_legacy` | 43 | Keys ~29548–29573 |
| `business_license_legacy` | 42 | Keys ~26304–26328 |
| `variance_legacy` | 28 | Keys ~34762–34788 |
| `utility_legacy` | 24 | Keys ~24222–24254 |
| `empty_extra` | 9 | Empty `extra` dict |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `main.status` (−1/0/1/2); if null, OpenGov / legacy STATUS strings in `extra` |
| `FILE_DATE` | `main.dateSubmitted` (UTC day); else `dateCreated`; else schema APPLIED key |
| `PERMIT_DATE` | `ISSUED` / schema issue keys for Active, Final, and issued-then-Inactive |
| `FINAL_DATE` | `FINALED` / schema final keys for Final only (sentinel dates rejected) |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,227 · Inactive 543 · Active 156 · In Review 21 · missing 53

Issues:
1. **53 rows with null `main.status`** (and null `STATUS_ORIGINAL` / `STATUS_NORMALIZED`). Extra still carries usable strings (`Stopped`, `EXPIRED`, `CANCELLED`, `DEAD FILE`, `Closed`, `Active`, …) across home-occupation, building, planning, and contact record types.
2. **1 inconsistency:** `STATUS_ORIGINAL=active` / `STATUS_NORMALIZED=Active` while `main.status=2` (complete) → should be Final.

When present, `main.status` maps cleanly and matches `STATUS_ORIGINAL`:

| `main.status` | `STATUS_ORIGINAL` | `STATUS_NORMALIZED` |
| ---: | --- | --- |
| −1 | stopped | Inactive |
| 0 | draft | In Review |
| 1 | active | Active |
| 2 | complete | Final |

**After:** Final 1,232 · Inactive 591 · Active 156 · In Review 21 · missing 0  
Flags: **FILLED 53 · FIXED 1**  
(Filled: Inactive 48 · Final 4 · Active 1)

### FILE_DATE

**Before:** 0 missing (100%).

- For nearly all rows, `FILE_DATE` equals the UTC calendar day of `dateSubmitted` / `dateCreated` (and matches named `APPLIED` / building `23692` when present).
- **24 modern form rows** had `FILE_DATE = dateCreated` while `dateSubmitted` fell on a later day (business licenses, encroachment, sewer lateral, etc.). Same pattern as Lomita: prefer submittal date.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 24**

### PERMIT_DATE

**Before:** 2,000 missing (100%).

Root cause: the processed sample never populated issuance dates, even though legacy extras and named `ISSUED` fields contain them for most building / encroachment / code / utility records.

Repairs:
- Fill from `ISSUED` (named) or schema-specific issue keys (`23706`, `23488`/`23477`, `25092`, `24224`, …).
- Populate for Active and Final; also keep issuance on Inactive rows that were issued then stopped/expired.
- Leave In Review without a permit date.

**After:** missing 609.  
Coverage: Active 68/156 (43.6%) · Final 821/1,232 (66.6%) · In Review 0/21 · Inactive 502/591 (84.9%).  
Named Final: 155/159 have `PERMIT_DATE`; building Final: 294/323.  
Remaining Active/Final gaps are mostly `form_extra` (modern applications without an issue timestamp).  
Flags: **FILLED 1,391 · FIXED 0**

### FINAL_DATE

**Before:** 2,000 missing (100%).

Root cause: same — finaling dates exist in `FINALED` / `23703` / peers but were never mapped. Some stamps are unusable:
- Placeholder `1/1/1950`
- Bulk migration dates `02/22/2022` and `09/01/2022` (common on Expired/Inactive building rows; rare on true Final)

Repairs:
- Fill Final rows from `FINALED` / schema final keys when the date is plausible (year in 1980–2035, not a sentinel, not before `FILE_DATE`).
- Do not attach `FINAL_DATE` to non-Final statuses.

**After:** missing 1,122 overall. Final 878/1,232 (71.3%); Active / In Review / Inactive 0%.  
Named Final: 153/159; building Final: 309/323.  
Largest remaining Final gaps: `form_extra` (269) and `public_works_legacy` without `36881` (38).  
Flags: **FILLED 878 · FIXED 0**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 53 | 1 | 53 → 0 |
| `FILE_DATE` | 0 | 24 | 0 → 0 |
| `PERMIT_DATE` | 1,391 | 0 | 2,000 → 609 |
| `FINAL_DATE` | 878 | 0 | 2,000 → 1,122 |

Ideal-field checklist after repair:
- `FILE_DATE` present for all statuses: **yes**
- `PERMIT_DATE` for Active/Final: **partial** (form_extra / some shells lack issue dates in DATA)
- `FINAL_DATE` for Final: **partial** (71.3%; limited by missing final timestamps and rejected sentinels)

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_eureka.py`
- Repaired sample: `AGENT_DATA_PATH/eureka_repaired_sample.parquet`
