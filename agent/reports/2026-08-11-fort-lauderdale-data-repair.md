# Fort Lauderdale (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (walking `(JURISDICTION, STATE)` pairs in file order after already-scripted cities through Citrus County / Coral Springs / West Palm Beach) was **Fort Lauderdale**. DATA is Accela Citizen Access JSON (`status` / `search_data` / `tasks` / `inspections`). STATUS_NORMALIZED gained **38** fills for previously unmapped portal statuses (2 TMP search stubs remain blank). FILE_DATE was filled on **1** void shell from an Application Submittal event. PERMIT_DATE already matched issuance workflow dates when present (**0** changes; ~70 Final rows have no issuance event). FINAL_DATE gained **348** fills (mostly Certification CC Issued) and **26** upgrades from Final Inspection Complete to a later CC/CO Issued date; **2** spurious non-Final FINAL_DATE values were cleared.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing FL repair scripts covered jurisdictions through West Palm Beach / Citrus County (and other already-scripted cities). **Fort Lauderdale** was the first without `agent/scripts/fl/data_repair_fl_fort_lauderdale.py`.

Sample size: **2,003** records.

## DATA schemas

| INFERRED_SCHEMA | Count | Notes |
| --------------- | ----: | ----- |
| `accela_basic`  | 1,679 | Dated task events; inspections absent/null |
| `accela_full`   |   316 | Dated task events + inspections list (newer scrape also has top-level `date`) |
| `accela_shell`  |     6 | Portal payload but no parseable dated task events |
| `search_only`   |     2 | Only `search_data` (TMP stubs, blank Status) |

Canonical source fields:

| Target field      | DATA source |
| ----------------- | ----------- |
| STATUS_NORMALIZED | `DATA.status` (else `search_data.Status`) |
| FILE_DATE         | `search_data.Date`, else `DATA.date`, else earliest Application Submittal / Intake / Document Submittal event |
| PERMIT_DATE       | Earliest `Issued` on Permit Issuance → Issuance → Revision Issuance; else Registration Issuance `Issued` / `Renewal Complete` |
| FINAL_DATE        | Certification `CC Issued` / `CO Issued` / `Final CO Issued`; else Inspection `Final Inspection Complete`; else inspections[] Pass on FINAL title |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,521 · Inactive 182 · Active 150 · In Review 110 · missing 40.

- Existing non-null mappings already matched `DATA.status` 1:1 (`Complete`/`Completed`→Final; `Issued`→Active; review-ish→In Review; `Void`/`Expired`/`Withdrawn`/`Disapproved`→Inactive). **0 FIXED**.
- **38** previously null rows filled from unmapped portal statuses:

  | DATA.status | → | n |
  | ----------- | - | -: |
  | Awaiting Permit Issuance | In Review | 10 |
  | Plan Set Submitted | In Review | 9 |
  | Pending Master | In Review | 8 |
  | Pending Master Corrections | In Review | 3 |
  | Awaiting Initial Fee Payment | In Review | 2 |
  | More Information Required | In Review | 2 |
  | Issuance Fees Paid | In Review | 1 |
  | Awaiting Revision Issuance | In Review | 1 |
  | Extension Approved | Active | 1 |
  | Purged | Inactive | 1 |

- **2** `search_only` TMP stubs have blank Status → left missing.

After: Final 1,521 · Inactive 183 · Active 151 · In Review 146 · missing 2.  
Flags: **FILLED 38 · FIXED 0**.

### FILE_DATE

Before: **1** missing. Ideal: populated for all records.

- Upstream FILE_DATE matched `search_data.Date` on **2,002** / 2,002 rows with a Date (**0** day mismatches). Top-level `date` (320 rows) also matches.
- **1** Inactive void row (`BLD-FUEL TANK DEMO-21080001`) has empty `search_data` → **FILLED** from Application Submittal `Void` event date `2021-08-25`.

After: **0** missing. Coverage by status: Active / Final / In Review / Inactive **100%**.  
Flags: **FILLED 1 · FIXED 0**.

### PERMIT_DATE

Before/after: **359** missing. Ideal: populated for Active and Final.

- When both an issuance-task date and PERMIT_DATE exist, they already agree (**0** mismatches across Permit Issuance / Issuance / Revision Issuance / Registration Issuance). Active coverage was already **100%** for the original Active set.
- **70** Final rows still lack any issuance-family event (property records, intake-only Complete, plan revisions without Revision Issuance, etc.) → not fillable from DATA.
- The newly mapped Active row (`Extension Approved`) also has no `Issued` event → PERMIT_DATE stays missing (Active coverage after repair **99.3%** = 150 / 151).

Flags: **FILLED 0 · FIXED 0**. Coverage after: Active **99.3%**; Final **95.4%** (1,451 / 1,521).

### FINAL_DATE

Before: 1,182 missing (702 of Final). Ideal: populated for Final; absent on non-Final.

- Upstream FINAL_DATE usually equals Inspection task `Final Inspection Complete` (max when multiple).
- **348** Final rows missing FINAL_DATE filled primarily from Certification `CC Issued` (plus a few `CO Issued` and passed FINAL inspections in the inspections array).
- **26** Final rows had FINAL_DATE = Final Inspection Complete while a later CC/CO Issued existed → **FIXED** to the certificate/signoff date.
- **2** non-Final rows incorrectly carried FINAL_DATE (Active + In Review) → cleared (**FIXED**).
- **354** Final rows remain without a Certification closeout, Final Inspection Complete, or passed FINAL inspection (common for HVAC changeouts, backflow, contractor registration/document updates, property records).

After: 836 missing overall; Final coverage **76.7%** (1,167 / 1,521). Non-Final FINAL_DATE coverage **0%**.  
Flags: **FILLED 348 · FIXED 28** (26 date upgrades + 2 clears).

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_fort_lauderdale.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.

## Artifacts

- Repaired sample: `AGENT_DATA_PATH/fort_lauderdale_repaired_sample.parquet`
