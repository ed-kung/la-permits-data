# Debary (FL) data repair

**Summary:** Among FL sample jurisdictions lacking a repair script, Debary was first alphabetically. Its DATA JSON is a Cocoa/Casselberry-style citizen portal payload. Upstream status mapping was already correct for almost all rows; the main defects were missing FILE_DATE (often fillable only via Issue Date), FILE_DATE stamped to late Review Completions instead of earliest Review Start, universally missing FINAL_DATE on Closed permits, and three null STATUS_NORMALIZED rows. The repair script fills/fixes these from `Status:`, `Permit Details['Issue Date:']`, Reviews, and Inspections.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Debary, FL (2,000 sample rows)
- Script: `agent/scripts/fl/data_repair_fl_debary.py` (`data_repair`)

## DATA schema

All rows share core keys (`Status:`, `Permit Details`, `Reviews`, `Inspections`, `Issue Date`, …). Top-level `Issue Date` is always null; issuance lives under `Permit Details['Issue Date:']`. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | Count |
| --- | ---: |
| issued_insp | 1,143 |
| issued | 579 |
| issued_insp_rev | 148 |
| issued_rev | 77 |
| minimal | 32 |
| rev | 19 |
| insp_rev | 1 |
| insp | 1 |

## Field assessment

### STATUS_NORMALIZED

| DATA `Status:` | Rows | Upstream STATUS_NORMALIZED |
| --- | ---: | --- |
| Closed | 1,599 | Final (correct) |
| Issued | 310 | Active (correct) |
| Expired | 35 | Inactive (correct) |
| Void | 20 | Inactive (correct) |
| Online Application Received | 17 | In Review (correct) |
| Under Review | 9 | In Review (correct) |
| Payment Required | 4 | In Review (correct) |
| Approved | 3 | Active (correct) |
| *(blank)* | 2 | null |
| CO Issued Date | 1 | null |

**Finding:** Mapping from `STATUS_ORIGINAL` was already right for 1,997/2,000 rows. The three nulls are repairable: blank `Status:` with Issue Date → Active; `CO Issued Date` → Final.

### FILE_DATE

- Missing on 1,768/2,000 rows. DATA has no dedicated application-date field.
- Of 232 populated FILE_DATE values, ~206 matched the *latest* Review Completion rather than the earliest Review Start (true submittal proxy); only ~23 already matched earliest Start.
- Reviews present on 249 rows; otherwise Issue Date is the only usable proxy.

### PERMIT_DATE

- When present, always matched `Permit Details['Issue Date:']` (1,947 agrees, 0 mismatches).
- Gaps: 1 Active (`Approved`, blank Issue Date but review Completions available), 13 Final Closed shells with blank Issue Date / no reviews, plus In Review / Inactive rows where issuance is absent or not required.

### FINAL_DATE

- Missing on all 2,000 rows despite 1,599 Closed/Final.
- Debary inspections are typed generically (e.g. “Building Inspection”), not “Final”; completion is inferred from latest passed inspection, else review Completion, else Issue Date for Closed / CO Issued.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 0 | 3 → 0 |
| FILE_DATE | 1,735 | 209 | 1,768 → 33 |
| PERMIT_DATE | 1 | 0 | 53 → 52 |
| FINAL_DATE | 1,588 | 0 | 2,000 → 412* |

\*412 remaining FINAL_DATE nulls are almost all non-Final statuses (correctly left empty); only **12 Final** rows still lack FINAL_DATE (Closed shells with no Issue Date, Reviews, or passed Inspections).

Coverage after repair:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- |
| Active | 315/315 (100%) | 315/315 (100%) | 0/315 (expected) |
| Final | 1,587/1,600 (99.2%) | 1,587/1,600 (99.2%) | 1,588/1,600 (99.2%) |
| In Review | 18/30 (60%) | 3/30 | 0/30 (expected) |
| Inactive | 47/55 (85.5%) | 43/55 | 0/55 (expected) |

## Not repairable from DATA

- 33 rows (mostly `minimal`) have neither dated Reviews nor Issue Date → FILE_DATE stays missing.
- 12 Final Closed shells with empty Issue Date / Reviews / Inspections → PERMIT_DATE and FINAL_DATE stay missing.
- ~1,722 FILE_DATE fills use Issue Date as a weak application proxy when Reviews are absent (no true file/submittal stamp in DATA).
- A few Payment Required (In Review) rows already carry Issue Date / PERMIT_DATE; status text is kept.
