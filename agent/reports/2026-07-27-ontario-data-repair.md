# Ontario (CA) data repair

**Summary:** Ontario was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status is now fully populated (**FILLED 2 · FIXED 8**): lagged `STATUS_ORIGINAL` mismatches against `DATA.status` were corrected, and two null-status rows were filled as In Review. `FILE_DATE` missingness fell from **1,920 → 2** (**FILLED 1,918**) using `search_data['Date Opened']`. `PERMIT_DATE` gained **13 FILLED** rows from `Issue Permit` / Issued events (Active/Final coverage still limited by empty legacy task shells). `FINAL_DATE` missingness fell from **1,984 → 1,440** (**FILLED 544 · FIXED 15**), filling from Construction Final / Finaled / CO Issued and correcting stale finals earlier than the Construction event.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Ontario, CA** (n=2,001)
- Script: `agent/scripts/ca/data_repair_ca_ontario.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Civic Access scrapes with top-level keys `status`, `tasks`, `search_data`, `more_details`, etc. A minority (~64) also carry `attachments` / unpaid-fee keys. Sub-schemas reflect which date sources are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,025 | Dated workflow events under `tasks` |
| `accela_search_only` | 757 | No task list; dates in `search_data` (mostly legacy Final) |
| `accela_shell` | 219 | Task shells present but no dated events |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (fallback: task event marks) |
| `FILE_DATE` | `search_data['Date Opened']`; else earliest Application Submittal event; else parseable `DATA.date` |
| `PERMIT_DATE` | `Issue Permit` → Issued (`status` or `Marked as`) |
| `FINAL_DATE` | `Construction` → Final / Finaled / CO Issued |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,324 · Active 310 · Inactive 190 · In Review 175 · missing 2

`DATA.status` maps cleanly when present:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Final | Final |
| Issued, Active | Active |
| Under Review, OTC, Applied, Ready to Issue, In P/R, Plan Check Fees Invoiced | In Review |
| Expired, Void, Withdrawn | Inactive |

Issues:
1. **8 mis-normalized rows** where `STATUS_ORIGINAL` lagged the live Accela status:
   - Final → Active (2) — Construction already Finaled; `STATUS_ORIGINAL=issued`
   - Issued → In Review (3) — `STATUS_ORIGINAL` still under review / otc
   - Under Review / OTC → Active (3) — `STATUS_ORIGINAL=issued` but Issue Permit still TBD or review ongoing
2. **2 null `STATUS_NORMALIZED`:** Plan Check Fees Invoiced → In Review; empty-status shell with only Application Submittal TBD → In Review.

OTC as a top-level status is kept as **In Review**: these rows typically have Application Submittal marked OTC but Issue Permit still TBD (not yet issued).

**After:** Final 1,326 · Active 308 · Inactive 190 · In Review 177 · missing 0  
Flags: **FILLED 2 · FIXED 8**

### FILE_DATE

**Before:** 1,920 missing (96.0%).

Root cause: upstream rarely copied `search_data['Date Opened']` into `FILE_DATE`. When both were present they already matched (56/56). `DATA.date` is unreliable here — often absent, a permit ID string, or Accela template dict junk.

Repairs:
1. Prefer `search_data['Date Opened']`.
2. Else earliest dated Application Submittal event.
3. Else parseable string `DATA.date` (reject IDs / template dicts).

**After:** 2 missing (both lack Date Opened and a parseable date source).  
Flags: **FILLED 1,918 · FIXED 0**

### PERMIT_DATE

**Before:** 1,119 missing (55.9%). Among Active/Final: 834 / 1,634 missing.

When an `Issue Permit` / Issued event exists, existing `PERMIT_DATE` already matched (844/844). Gaps are almost entirely legacy `accela_search_only` / `accela_shell` rows with no issuance events.

Repairs (Active / Final only): fill from earliest `Issue Permit` → Issued.

**After:** missing 1,106 overall; Active 212/308 (68.8%) · Final 598/1,326 (45.1%) have `PERMIT_DATE`.  
Flags: **FILLED 13 · FIXED 0**

Remaining Active/Final gaps (824) have no Issued event in `DATA` and are not fillable from this scrape.

### FINAL_DATE

**Before:** 1,984 missing (99.2%). Among Final: 1,309 / 1,324 missing. No spurious finals on non-Final rows.

Root cause: upstream almost never copied Construction finaling events. Where both existed, 15 rows had an earlier `FINAL_DATE` than Construction Final / Finaled / CO Issued (stale proxy) → FIXED to the Construction event.

Repairs (Final only):
1. Prefer latest Construction → Final / Finaled / CO Issued.
2. Else any Final / Finaled / CO Issued mark on other tasks.

**After:** missing 1,440 overall; Final 561/1,326 (42.3%) have `FINAL_DATE`.  
Flags: **FILLED 544 · FIXED 15**

Remaining Final gaps (765) are mostly pre-~2015 search-only / empty-shell rows with no Construction events.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 2 | 8 | 2 → 0 |
| `FILE_DATE` | 1,918 | 0 | 1,920 → 2 |
| `PERMIT_DATE` | 13 | 0 | 1,119 → 1,106 |
| `FINAL_DATE` | 544 | 15 | 1,984 → 1,440 |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_ontario.py`
