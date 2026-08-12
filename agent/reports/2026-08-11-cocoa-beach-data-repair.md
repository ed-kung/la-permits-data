# Cocoa Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Cocoa Beach**. DATA is a uniform CitizenServe payload (`main` / `extra` / `location`, 2,000 rows). STATUS_NORMALIZED needed **17 FIXED** (5 Active→Final from `main.status==2`; 12 Voided legacy citations Final→Inactive). FILE_DATE reached **100%** coverage (**3 FILLED**, **651 FIXED**): prefer `dateSubmitted` over `dateCreated`, and replace Legacy Civil Citations import-day FILE values with historical `CitDate`. PERMIT_DATE: **442 FILLED** (mostly legacy `CitDate`, plus 4 modern `DATE ISSUED`). FINAL_DATE: **97 FILLED** for Final rows (7.2%) from CE `Closing date`, reclaimed-water `Date:`, and sparse event/ROW end dates. Modern BLDG/BTR rows still lack issuance/CO timestamps in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered earlier jurisdictions through Cocoa; **Cocoa Beach** was the first without `agent/scripts/fl/data_repair_fl_cocoa_beach.py`.

Sample size: **2,000** records.

## DATA schemas

| INFERRED_SCHEMA | Count |
| --- | ---: |
| `citizenserve_building` | 825 |
| `citizenserve_legacy_citations` | 440 |
| `citizenserve_btr` | 340 |
| `citizenserve_draft` | 147 |
| `citizenserve_reclaimed` | 123 |
| `citizenserve_vacation_rental` | 59 |
| `citizenserve_code` | 47 |
| `citizenserve_other` | 15 |
| `citizenserve_citations` | 4 |

All rows share the same top-level envelope. Variants are content/form splits by `main.recordTypeName` (Legacy Civil Citations classified before the draft check so `CitDate` still repairs FILE_DATE on unsubmitted shells).

Canonical source fields:

| Target field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `main.status` (`0`→In Review, `1`→Active, `2`→Final, `-1`→Inactive); Voided legacy citations (`Status`/`Status Desc`) → Inactive |
| FILE_DATE | Legacy `CitDate` (else `Entered On`); else `dateSubmitted`; else `dateCreated` |
| PERMIT_DATE | `DATE ISSUED` (modern citations/CE); `CitDate` (legacy citations) for Active/Final/Inactive |
| FINAL_DATE | CE `Closing date` / compliance / abatement; reclaimed `Date:`; building/other `End Date` / garage-sale / event end (Final only) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,349 · Active 488 · In Review 149 · Inactive 14 · missing 0.

- Upstream mapping from `STATUS_ORIGINAL` (`complete`/`active`/`draft`/`stopped`) matches `main.status` on **1,983 / 2,000** rows.
- **5** rows still labeled Active/`active` while `main.status==2` (complete) → FIXED to Final.
- **12** Legacy Civil Citations with `Status Desc=Voided` kept `main.status==2` / Final → FIXED to Inactive.
- No missing values → **FILLED 0 · FIXED 17**.

After: Final 1,342 · Active 483 · In Review 149 · Inactive 26.

### FILE_DATE

Before: 3 missing (99.85% populated). Ideal: populated for all records.

- Non-legacy rows: FILE_DATE already matches `dateSubmitted` on most submitted records; **211** have FILE on `dateCreated` while submit falls on a later calendar day → FIXED to submittal date.
- **3** rows (null `dateCreated`, present `dateSubmitted`) had missing FILE_DATE → FILLED.
- Drafts (`main.status==0`) correctly keep `dateCreated` (no `dateSubmitted`).
- Legacy Civil Citations (440): FILE_DATE is the Jan-2025 CitizenServe import day; `CitDate` is the historical citation date (years earlier) → FIXED on all 440.

After: 0 missing (100%).  
Flags: **FILLED 3 · FIXED 651**.

| INFERRED_SCHEMA | FIXED | FILLED |
| --- | ---: | ---: |
| `citizenserve_legacy_citations` | 440 | 0 |
| `citizenserve_building` | 128 | 1 |
| `citizenserve_btr` | 60 | 2 |
| `citizenserve_vacation_rental` | 19 | 0 |
| `citizenserve_reclaimed` | 2 | 0 |
| `citizenserve_other` | 2 | 0 |

### PERMIT_DATE

Before: 2,000 missing. Ideal: populated for Active and Final.

- Modern BLDG / BTR / vacation-rental forms expose no issue/CO date in `extra`. `expirationDate` is expiry (~180 days after file for many building rows) and `lastUpdatedDate` is not a safe issuance proxy → left missing.
- Legacy Civil Citations: `CitDate` filled as citation issuance for Active/Final/Inactive → **438** of the 440 (2 In Review shells skipped).
- Modern Civil Citations: `DATE ISSUED` → **4 FILLED** (Active).

After: 1,558 missing. Coverage: Active **0.8%** (4/483); Final **31.7%** (426/1,342); Inactive **46.2%** (12/26, voided citations).  
Flags: **FILLED 442 · FIXED 0**.

### FINAL_DATE

Before: 2,000 missing. Ideal: populated for Final.

- No building-permit final/CO field in DATA.
- DS Code Enforcement Final: `Closing date` → **23 FILLED**.
- Reclaimed Water Inspection Final: form `Date:` (inspection day) → **67 FILLED**.
- Sparse Final ROW / garage-sale / other end dates → **7 FILLED**.
- Legacy citations have payment/collections status text but no close timestamp → FINAL_DATE stays missing.

After: 1,903 missing. Final coverage **7.2%** (97/1,342).  
Flags: **FILLED 97 · FIXED 0**.

## Repair script performance

Script: `agent/scripts/fl/data_repair_fl_cocoa_beach.py`  
Function: `data_repair(df)`  
Artifact: `AGENT_DATA_PATH/cocoa_beach_repaired_sample.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 17 | 0 → 0 |
| FILE_DATE | 3 | 651 | 3 → 0 |
| PERMIT_DATE | 442 | 0 | 2,000 → 1,558 |
| FINAL_DATE | 97 | 0 | 2,000 → 1,903 |

Post-repair coverage by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 483 | 100% | 0.8% | 0% |
| Final | 1,342 | 100% | 31.7% | 7.2% |
| In Review | 149 | 100% | 0% | 0% |
| Inactive | 26 | 100% | 46.2% | 0% |
