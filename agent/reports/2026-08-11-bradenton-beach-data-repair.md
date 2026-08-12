# Bradenton Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (sorted `(JURISDICTION, STATE)` order) was Bradenton Beach (2,000 records). DATA is a flat portal export with four key-layout variants and only one usable date field (`Issue Date` → issuance). STATUS_NORMALIZED: 1 FILLED + 277 FIXED (nulls 1→0), mainly reclassifying Fulfilled Lien Searches from In Review→Final and syncing stale STATUS_ORIGINAL to current `DATA.Status`. FILE_DATE and FINAL_DATE are entirely absent from DATA and stay missing. PERMIT_DATE: 16 FILLED from parseable `Issue Date` values (gaps 331→315).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Bradenton Beach, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/fl/data_repair_fl_bradenton_beach.py`
- Artifact: `AGENT_DATA_PATH/bradenton_beach_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing keys |
| --- | ---: | --- |
| `flat_space_wd` | 1,464 | `Permit #` + `Issue Date` + `Work Description` |
| `flat_hash` | 265 | `Permit#` + `Issue Date` (no Work Description) |
| `flat_hash_wd` | 221 | `Permit#` + `Issue Date` + `Work Description` |
| `flat_space` | 50 | `Permit #` + `Issue Date` (no Work Description) |

Shared repair fields: `Status`, `Issue Date`, `Permit Type`. No application or finalization date exists in any schema. Address key also varies (`Address ` vs `Address`) but is unused for repair.

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,082; In Review 468; Active 332; Inactive 117; **null 1**.
- Canonical map from `DATA.Status`: Closed/Fulfilled → Final; Issued/Approved → Active; Online Application Received/Under Review/Incomplete Permit → In Review; Denied/Void/Withdrawn/Expired* → Inactive.
- Root causes of incorrect values:
  - **Fulfilled Lien Search (260)** labeled In Review via STATUS_ORIGINAL — Fulfilled means the search completed → **FIXED** to Final.
  - **Stale STATUS_ORIGINAL vs current `DATA.Status`** (17): Closed rows still Active/In Review/Inactive (9); Issued rows still In Review/Final (8).
  - **Incomplete Permit (1)** left null → **FILLED** as In Review.
- After: Final 1,350; Active 333; In Review 201; Inactive 116; **null 0**.

### FILE_DATE

- Ideal: populated for all records.
- Before/after: **2,000 missing**. DATA has no application/submittal date. Pre-issuance rows put work-description text into `Issue Date`, not a filed date.
- Repair: 0 FILLED / 0 FIXED.

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Source: `Issue Date` when it is a real calendar date (1,685 rows). Every existing PERMIT_DATE already matched that date (0 mismatches → 0 FIXED).
- **16 FILLED** where Issue Date parsed but PERMIT_DATE was null (14 Issued, 1 Closed, 1 Fulfilled).
- 315 still missing: `Issue Date` holds non-date text (work descriptions) — typical for Online Application Received, Under Review, Approved-unissued, Void/Withdrawn, and a few Closed/Fulfilled Lien Search rows.
- After status repair: Active **279/333 (83.8%)** (54 Approved with description-in-Issue-Date); Final **1,340/1,350 (99.3%)**.

### FINAL_DATE

- Ideal: populated for Final.
- Before/after: **2,000 missing**. Closed/Fulfilled expose no finaled, CO, or completion timestamp — only Issue Date (issuance).
- Repair: 0 FILLED / 0 FIXED. All Final rows remain without FINAL_DATE.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 277 | 1 → 0 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 16 | 0 | 331 → 315 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

STATUS FIXED transitions: In Review→Final 261; Active→Final 7; In Review→Active 7; Final→Active 1; Inactive→Final 1.

Ideal-field coverage after repair:

- FILE_DATE: 0% of all records (no source in DATA)
- PERMIT_DATE: 83.8% of Active; 99.3% of Final
- FINAL_DATE: 0% of Final (no source in DATA)

## Artifacts

- `agent/scripts/fl/data_repair_fl_bradenton_beach.py`
- `AGENT_DATA_PATH/bradenton_beach_repaired_sample.parquet`
