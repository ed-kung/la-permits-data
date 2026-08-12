# Palm Springs (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script after Port Orange was Palm Springs (2,000 rows). DATA is CityView / CentralSquare portal JSON (`status` / `details.created|issued|closed` / `timeline`). Upstream STATUS_NORMALIZED naively mapped top-level `Open`→In Review even when Issued/Closed stamps (or Expired/Cancelled detail status) were present — **1,063** status FIXED (671→Final, 345→Active, 46→Inactive, plus 1 Active→Final). FILE_DATE already matched `details.created` (37 Munis shells stay missing). PERMIT_DATE matched `details.issued` when present; **43** spurious stamps cleared on Inactive. FINAL_DATE carried **136** `1899-11-30` SQL sentinels plus other non-Final closes — **175** FIXED (cleared); Final coverage after repair is **1,420 / 1,422 (99.9%)**.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in first-appearance order. Existing FL repair scripts covered through Port Orange. **Palm Springs** was the first without `agent/scripts/fl/data_repair_fl_palm_springs.py`.

Sample size: **2,000** records.

## DATA schemas

CityView / CentralSquare community portal payload. Top-level keys include `id`, `type`, `number`, `status`, `details`, `timeline`, `customFields`, `contacts`, plus optional `lastUpdDate`, `entryForms`, `canMakeOperations`.

| INFERRED_SCHEMA prefix | Meaning |
| ---------------------- | ------- |
| `cityview_portal_*` | Has `entryForms` and/or `canMakeOperations` |
| `cityview_updated_*` | Has `lastUpdDate`, no portal extras |
| `cityview_*` | Core payload only |

Content suffixes: `_issued_closed`, `_issued`, `_closed`, `_created`, `_minimal`.

Largest buckets: `cityview_issued_closed` 883 · `cityview_issued` 318 · `cityview_portal_closed` 267 · `cityview_updated_issued_closed` 201.

Canonical source fields:

| Target field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | Top-level `status`, with Expired/Cancelled/Withdrawn detail-status → Inactive; real `details.closed` → Final; real `details.issued` → Active |
| FILE_DATE | `details.created` |
| PERMIT_DATE | `details.issued` |
| FINAL_DATE | `details.closed` (years &lt; 1980 rejected as sentinel, notably `1899-11-30`) |

## Field assessments

### STATUS_NORMALIZED

Before: In Review 1,124 · Final 750 · Active 115 · Inactive 11 · missing 0.  
After: Final 1,422 · Active 459 · In Review 62 · Inactive 57 · missing 0.

- Upstream mapped only top-level `status` (`Open`→In Review, `Closed`→Final, `Issued`/`Approved`→Active, `Void`→Inactive). That is too coarse for this portal.
- **FIXED (1,063):**
  - In Review → Final **671**: Open rows with a real Closed stamp (mostly Historical Permits; also a few with detail status `Closed`)
  - In Review → Active **345**: Open rows with Issued but no real Closed (includes Munis `details.status=Active`)
  - In Review → Inactive **46**: Open rows with Expired / Cancelled detail status
  - Active → Final **1**: Issued row that also carried a real Closed stamp
- Remaining In Review (**62**) are true open applications (no Issued/Closed).

Flags: **FILLED 0 · FIXED 1,063**.

### FILE_DATE

Before/after: **37 missing**. Ideal: populated for all records.

- When `details.created` is present (1,963 rows), FILE_DATE matches it exactly at day resolution — no FILLED/FIXED needed.
- All **37** gaps are Munis import shells with blank `created` (issued is present but is an issuance stamp, not a file/application date) → not filled.
- No incorrect non-null FILE_DATE values found.

Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: **441 missing**. After: **484 missing** (cleared spurious values). Ideal: populated for Active and Final.

- When `details.issued` is present (1,559 rows), upstream PERMIT_DATE matched it exactly.
- After status repair: Active **440 / 459 (95.9%)**; Final **1,076 / 1,422 (75.7%)**.
- Active gaps (**19**): Issued portal rows with blank `details.issued` and undated timeline tasks — cannot invent an issue date.
- Final gaps (**346**): Closed rows (often code-enforcement / short type codes) with blank Issued.
- **43 FIXED** clears of PERMIT_DATE on Inactive (Expired/Cancelled/Void with an Issued stamp that should not remain under the ideal rule).
- In Review correctly ends with **0** PERMIT_DATE (issued Open rows were reclassified to Active/Final).

Flags: **FILLED 0 · FIXED 43**.

### FINAL_DATE

Before: **405 missing**. After: **580 missing** (cleared sentinels / non-Final closes). Ideal: populated for Final.

- Upstream FINAL_DATE was a straight copy of `details.closed`, including **136** `1899-11-30` SQL empty-date sentinels on Open/Historical rows.
- Also present on non-Final statuses: In Review 835 (incl. sentinels), Inactive 11, Active 1.
- **175 FIXED** (all clears): 136 sentinel finals on rows reclassified to Active; 39 finals on Inactive (Void/Expired/Cancelled).
- Open→Final rows already carried a real Closed stamp upstream, so no FILLED was needed for those.
- Final after repair: **1,420 / 1,422 (99.9%)**; the **2** gaps are Closed rows with blank `details.closed`.
- Non-Final statuses correctly end with FINAL_DATE null; **0** years &lt; 1980 remain.

Flags: **FILLED 0 · FIXED 175**.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_palm_springs.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.
- Conventions aligned with `agent/scripts/fl/data_repair_fl_port_orange.py` and `agent/scripts/ny/data_repair_ny_ny.py`.

## Performance snapshot

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 1,063 | 0 | 0 |
| FILE_DATE | 0 | 0 | 37 | 37 |
| PERMIT_DATE | 0 | 43 | 441 | 484 |
| FINAL_DATE | 0 | 175 | 405 | 580 |

Chronology after repair: **6** FILE&gt;PERMIT and **2** PERMIT&gt;FINAL inversions — all present in source `details` dates (created after issued, or closed before issued), not introduced by the repair.

Ideal-coverage gaps remaining: Active/Final missing PERMIT_DATE **365**; Final missing FINAL_DATE **2**; FILE_DATE missing **37**; STATUS_NORMALIZED missing **0**.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_palm_springs.py`
- Repaired parquet: `AGENT_DATA_PATH/repaired/permits_fl_palm_springs_repaired.parquet`
