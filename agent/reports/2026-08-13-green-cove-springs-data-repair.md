# Green Cove Springs (FL) data repair

Green Cove Springs was the first `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing `agent/scripts/{state}/data_repair_*.py` script. Its DATA payloads are SmartGov community-portal JSON. A repair script now fills or corrects `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from `Build Status` and `My Project` dates, leaving only two empty shells and one Finaled record without a completion stamp unrepaired.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Green Cove Springs, FL** (2,000 sample rows)
- Script: `agent/scripts/fl/data_repair_fl_green_cove_springs.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_green_cove_springs_repaired.parquet`

## DATA shape / INFERRED_SCHEMA

All rows share the SmartGov key set (`Department`, `My Project`, `Build Status`, `Permit Number`, fees/contacts/inspections arrays, etc.). Schema variants:

| INFERRED_SCHEMA   | n    | Notes                                      |
| ----------------- | ---- | ------------------------------------------ |
| smartgov_full     | 1442 | includes `ProjectDescription`              |
| smartgov_no_desc  | 554  | has `Parcel Number`, no description        |
| smartgov_minimal  | 4    | core keys only (incl. 2 empty shells)      |

Canonical fields used:

- Status: `Build Status` (plus Closed / Issued date overrides; null `Build Status` inferred from `My Project` dates)
- `FILE_DATE` ← `My Project.Submitted` (fallback `Created`)
- `PERMIT_DATE` ← `My Project.Issued` (fallback `Approved`; SmartGov `" - -"` treated as null)
- `FINAL_DATE` ← `My Project.Closed` (fallback latest passed Final / CO inspection)

## Findings by field

### STATUS_NORMALIZED

**Before:** Final 1,112 · null 638 · Inactive 97 · Active 96 · In Review 57.

Main failure modes:

1. **Null status (638)** — mostly null `Build Status` (542) despite usable `My Project` dates; also unmapped `Expired: <date>` (74), `Insufficient Submittal` (11), and a handful of Closed / Issued / review statuses with blank `STATUS_ORIGINAL`.
2. **Stale normalization vs DATA** — `STATUS_ORIGINAL` lagged behind `Build Status`: Closed shells still labeled Active/In Review/Inactive; Issued shells labeled In Review; Expired shells labeled Active/In Review/Final; Finaled labeled Active.

Repair maps Expired* → Inactive; Closed / Finaled / CO → Final; Issued (or any Issued date) → Active; review-like statuses → In Review; null `Build Status` inferred from Closed → Issued → Submitted/Created/Approved.

**After:** Final 1,292 · Active 269 · In Review 253 · Inactive 184 · null **2**.  
Flags: **FILLED 636**, **FIXED 57**. Remaining nulls are two empty shells with no status or dates.

### FILE_DATE

Almost complete already (5 missing). Three rows had fillable Submitted/Created stamps; two empty shells have no dates in DATA. No mismatches vs Submitted.

**After:** missing **2**. Flags: **FILLED 3**, **FIXED 0**. Coverage 99.9%.

### PERMIT_DATE

**Before:** 669 missing. Ideal gaps concentrated in Final/Closed rows whose `Issued` is the SmartGov placeholder `" - -"` but `Approved` is populated (license / quick-close style cases), plus Active/Final rows that gained status from null shells.

**After:** missing 298 overall; Active **100%** and Final **99.9%** populated. Flags: **FILLED 371**, **FIXED 0**. One Closed Final (`SPL-22-003`) still lacks PERMIT_DATE — both Issued and Approved are blank in DATA.

In Review correctly has 0 PERMIT_DATE after repair (Issued shells that were In Review were promoted to Active and filled).

### FINAL_DATE

**Before:** 749 missing. Closed shells mislabeled Active had Closed dates in DATA but no FINAL_DATE; some Final/Closed rows simply never copied Closed; one Finaled had a usable Final inspection; one Inactive Expired row carried a spurious FINAL_DATE.

**After:** Final **1,291 / 1,292 (99.9%)** have FINAL_DATE; non-Final statuses have none. Flags: **FILLED 41**, **FIXED 1** (cleared spurious FINAL on Inactive). One Finaled (`BN-24-004`) remains without FINAL_DATE — Closed blank and empty inspections.

## Repair performance summary

| Field             | FILLED | FIXED | Missing before → after |
| ----------------- | -----: | ----: | ---------------------- |
| STATUS_NORMALIZED |    636 |    57 | 638 → 2                |
| FILE_DATE         |      3 |     0 | 5 → 2                  |
| PERMIT_DATE       |    371 |     0 | 669 → 298              |
| FINAL_DATE        |     41 |     1 | 749 → 709              |

Ideal-coverage residuals (not recoverable from DATA):

- STATUS_NORMALIZED null: 2 empty shells
- FILE_DATE missing: same 2 empty shells
- Active/Final missing PERMIT_DATE: 1 (`SPL-22-003`, blank Issued/Approved)
- Final missing FINAL_DATE: 1 (`BN-24-004`, blank Closed, no Final inspection)

Chronology note: 7 rows have Submitted after Issued (and 1 has Closed before Issued) in the agency payload itself — typically amendment / re-submittal patterns. The repair preserves agency stamps rather than inventing order.

## Not repairable from DATA

- Empty SmartGov shells (null everything under `My Project` / `Build Status`)
- Finaled with no Closed stamp and no passed Final/CO inspection
- Closed Final with neither Issued nor Approved
