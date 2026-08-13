# Sanford (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Sanford**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`). Upstream left `Finaled - CO` / `Finaled - CC` / `Information Required` / blank Status unmapped (117 nulls), often copied latest Review Completion into FILE_DATE instead of Application Intake Start, never populated FINAL_DATE, and carried 11 OOR PERMIT_DATE sentinels plus many 2030–2042 Issue Date corruptions. Repair FILLED 94 and FIXED 17 STATUS values (23 empty historic shells remain null). FILE_DATE FIXED 908 / FILLED 12. PERMIT_DATE FIXED 11 OOR clears (no safe fills once 2030+ Issue Dates are rejected). FINAL_DATE FILLED 246 Closed/Finaled shells with real Final*/CO stamps (placeholders `2000-01-01` / `2018-01-01` excluded).

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Sanford, FL** → `agent/scripts/fl/data_repair_fl_sanford.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share portal keys `Status:`, `Permit #:`, `Issue Date` (always null), `Permit Details`, `Inspections`, `Reviews`. Key-set prefixes:

| Schema prefix | Distinguishing extras |
| --- | --- |
| `portal_core` | Minimal core form |
| `portal_form` | Residential `Type of Work` / owner-builder fields |
| `portal_commercial` | `Type of work - commercial` |
| `portal_row` | ROW `Start Date` / `Completion Date` / `ROW Name` |

Content suffixes split by recoverable dates (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`). Largest buckets: `portal_form_issued_finaled` (581), `portal_form_issued` (292), `portal_commercial_issued_finaled` (233).

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (blank/unmapped inferred from usable Issue Date / Final* stamps) |
| FILE_DATE | Application Intake Start → earliest non-certificate Review Start/Completion on/before Issue → ROW `Start Date` |
| PERMIT_DATE | `Permit Details["Issue Date:"]` for Active / Final / Inactive (years outside 1980–2026 and `2000-01-01` / `2018-01-01` rejected) |
| FINAL_DATE | Latest passed Final*/CO inspection → Certificate Review Completion → `Completion Date`; Final only |

Status map: Closed / Finaled - CO / Finaled - CC → Final; Issued / Approved / Issued - Need NOC → Active; Under Review / On Hold / Online Application Received / Information Required / Corrections Requested → In Review; Withdrawn / Expired / Denied / Disapproved → Inactive. In Review shells that already carry a usable Issue Date are upgraded to Active.

## Field assessments

### STATUS_NORMALIZED

| Status: | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Issued | 1,111 | Active 1,111 | Correct |
| Closed | 365 | Final 365 | Correct |
| Under Review | 145 | In Review 145 | Correct (12 upgraded to Active when Issue Date present) |
| Withdrawn | 117 | Inactive 117 | Correct |
| Approved | 86 | Active 86 | Correct |
| Finaled - CO | 56 | null 56 | Unmapped → Final |
| Finaled - CC | 18 | null 18 | Unmapped → Final |
| (blank) | 25 | null 25 | Empty shells; 2 inferred, 23 stay null |
| Information Required | 17 | null 17 | Unmapped → In Review |
| Online Application Received | 16 | In Review 16 | Correct (3 upgraded to Active w/ Issue Date) |
| Expired | 18 | Inactive 18 | Correct |
| Issued - Need NOC | 11 | Active 11 | Correct |
| On Hold | 6 | In Review 6 | Correct (2 upgraded to Active w/ Issue Date) |
| Denied / Disapproved | 8 | Inactive 8 | Correct |
| Corrections Requested | 1 | null 1 | Unmapped → In Review |

**Root causes:**
- **Unmapped Status values:** `Finaled - CO`, `Finaled - CC`, `Information Required`, `Corrections Requested`, and blank `Status:` were absent from the upstream normalizer (117 nulls).
- **Status lag vs Issue Date:** 17 Under Review / On Hold / Online Application Received shells already had a usable Issue Date → FIXED to Active.

**Repair performance:** FILLED 94, FIXED 17; missing 117 → 23. After: Active 1,226; Final 440; In Review 168; Inactive 143; null 23 (empty historic shells with no Reviews/Inspections).

### FILE_DATE

Ideal: populated for all records.

- Upstream FILE_DATE matched the **latest Review Completion** on 1,169 / 1,364 populated rows — i.e. plan-review finish, not application/submittal.
- Correct source is **Application Intake Start** (1,160 rows have it); when present it matched upstream FILE_DATE on only 369 rows and disagreed on 782.
- **908 FIXED** to Intake / early Review Start (on/before Issue); **12 FILLED** where FILE was null but an application source existed.
- Post-issue FILE values with no application source are cleared; Intake Starts after Issue are ignored (eliminates FILE > PERMIT inversions).

Coverage after repair: Active 76.6%; Final 50.5%; In Review 46.4%; Inactive 95.1%. Remaining gaps are mostly older Closed/Issued shells with empty `Reviews`. Missing 636 → 625.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Top-level `Issue Date` is always null; usable stamp is `Permit Details["Issue Date:"]` (1,619 non-empty strings, but many corrupt).
- **116 Issue Dates in 2030–2042** are systematic corruption (filtered; `_MAX_YEAR=2026`). Also reject `2000-01-01` / `2018-01-01` placeholders.
- Existing in-range PERMIT_DATE values already matched Issue Date (**0 calendar mismatches** among usable pairs).
- **11 FIXED:** cleared OOR/sentinel PERMIT_DATE values (1951–era / out-of-range).
- **0 FILLED:** every previously “missing but Issue Date present” case used a 2030+ corrupt Issue Date — correctly left missing rather than filled.
- **17 FIXED clears** of spurious PERMIT_DATE on In Review (included in status-driven clear path).

Coverage after repair: Active 1,153/1,226 (94.0%); Final 308/440 (70.0%); In Review 0/168; Inactive 31/143. Active/Final still missing PERMIT_DATE: 205 (Closed 89, Issued 49, Finaled - CO 43, Approved 24) — blank or corrupted Issue Date only.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- **Every sample row had FINAL_DATE null** before repair.
- **246 FILLED** from passed Final*/CO inspections (preferred), else Certificate Review Completion / ROW Completion Date.
- Excluded migration placeholders `01/01/2000` (29 Final* rows) and `01/01/2018` (97 Final* rows) that would otherwise invent false finals.
- Non-Final correctly have no FINAL_DATE after repair.

Coverage after repair: Final 246/440 (55.9%); Active / In Review / Inactive 0%. Still missing FINAL on 194 Final rows (Closed 151, Finaled - CO 43) with no usable final stamp. Date-order: FILE>PERMIT 0, FILE>FINAL 0, PERMIT>FINAL 1 (BC20-000240: Issue 2020-06-04 vs Final insp 2020-05-26 — source quirk).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 94 | 17 | 117 → 23 |
| FILE_DATE | 12 | 908 | 636 → 625 |
| PERMIT_DATE | 0 | 11 | 497 → 508 |
| FINAL_DATE | 246 | 0 | 2,000 → 1,754 |

PERMIT_DATE missing count rises by 11 because OOR sentinels were cleared without a replacement Issue Date.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_sanford.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_sanford_repaired.parquet`
