# Portland (TX) data repair

**Summary:** Portland was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. Its DATA column is a SmartGov portal payload (`Build Status` + `My Project` dates). Of 2,000 sample rows, the repair fills/fixes 446 status values (412→6 missing), fills 11 FILE_DATEs, 50 PERMIT_DATEs, and fills/fixes 31 FINAL_DATEs. After repair, Active/Final have near-complete FILE/PERMIT coverage; Final has FINAL_DATE on 98.7% of usable rows. Remaining gaps are empty SmartGov shells and FINALED rows with neither Closed nor a passed Building Final inspection.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in sample order. Existing TX scripts covered through Odessa / Nacogdoches / La Marque; **Portland, TX** was the first missing (`agent/scripts/tx/data_repair_tx_portland.py`).

## DATA schema

SmartGov community portal JSON (same family as La Marque / Bellaire / Anna):

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| smartgov_full | 1,693 | `ProjectDescription` + `Parcel Number` + core keys |
| smartgov_no_desc | 231 | Parcel Number, no description |
| smartgov_no_parcel | 64 | Core keys only |
| smartgov_empty | 11 | Blank `My Project`, null `Build Status` |
| smartgov_minimal | 1 | Missing Department / Permit Type |

Canonical fields:

- **STATUS_NORMALIZED** ← `Build Status` (with Closed/Issued date overrides)
- **FILE_DATE** ← `My Project.Submitted`, else `Created`
- **PERMIT_DATE** ← `My Project.Issued`, else `Approved`
- **FINAL_DATE** ← `My Project.Closed`, else latest passed Building Final / COO inspection (including `Bureau Veritas Passed`)

## Findings by field

### STATUS_NORMALIZED

Before: Final 943, Inactive 426, null 412, Active 138, In Review 81.

Main problems:

1. **Null status (~412):** ~178 `Expired: M/D/YYYY` never mapped; ~169 null `Build Status` with Issued date (→ Active); ~28 with Closed (→ Final); ~31 Submitted-only (→ In Review).
2. **Expired labeled Active (~8):** sticky Inactive unless later Closed.
3. **Closed / CO labeled Active (~17):** `CLOSED` or `Cerificate of Occupancy` (agency typo) with Closed date still Active → Final.
4. **Application Complete labeled Final (~6):** application-stage status with no Issued/Closed → In Review.
5. **ISSUED labeled In Review (~4):** Issued date present → Active.
6. **WITHDRAWN:** keep Inactive even when SmartGov stamps Closed (admin close, not finaled).

After: Final 982, Inactive 614, Active 286, In Review 112, null 6 (empty shells only). **FILLED 406, FIXED 40.**

### FILE_DATE

Already matched Submitted/Created on nearly all rows. **FILLED 11** from My Project; **4** remain missing (empty shells). No incorrect non-missing values found. Ideal: populated for all records — achieved on all usable rows (100% for Active/Final/In Review/Inactive after repair).

### PERMIT_DATE

**FILLED 50** for Active/Final/Inactive rows that had Issued/Approved but missing PERMIT_DATE. **163** still missing overall (mostly In Review with no issuance, plus Expired without Issued/Approved). Active: 100% populated. Final: 981/982 (one Final burial/wind permit lacks Issued/Approved). No date-order violations (FILE ≤ PERMIT ≤ FINAL).

### FINAL_DATE

**FILLED 23** from Closed (and inspection fallback where applicable); **FIXED 8** clearing spurious FINAL_DATE on non-Final rows (e.g. WITHDRAWN). Final coverage after: **969/982 (98.7%)**. Remaining 13 are `FINALED` with Closed blank and no passed Building Final / COO inspection in DATA.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 406 | 40 | 412 → 6 |
| FILE_DATE | 11 | 0 | 15 → 4 |
| PERMIT_DATE | 50 | 0 | 213 → 163 |
| FINAL_DATE | 23 | 8 | 1,046 → 1,031 |

Post-repair coverage (usable schemas only):

- Active: FILE 100%, PERMIT 100%, FINAL 0% (correct)
- Final: FILE 100%, PERMIT 99.9%, FINAL 98.7%
- In Review: FILE 100%, PERMIT 0%, FINAL 0% (correct)
- Inactive: FILE 100%, PERMIT 92.5%, FINAL 0% (correct)

Date order checks: FILE > PERMIT = 0; PERMIT > FINAL = 0; FILE > FINAL = 0.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_portland.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_tx_portland_repaired.parquet`
