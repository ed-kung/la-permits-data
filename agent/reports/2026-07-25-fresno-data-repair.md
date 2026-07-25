# Fresno (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Fresno — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Across 2,000 Accela Citizen Access rows, blank statuses were filled (12), stale Issued/Comments Delivered statuses with completion events were promoted to Final (25), `FILE_DATE` needed no changes, `PERMIT_DATE` was already correct wherever an Issued event exists, and `FINAL_DATE` was filled from Final CO events (25) and corrected from earliest→latest Final Inspection Complete (300) while 8 spurious finals on Rejected rows were cleared. After repair every row has a status and `FILE_DATE`; Active/Final have ~98% `PERMIT_DATE`; Final has 57.9% `FINAL_DATE` (remaining gaps are Accela TBD/empty inspection workflows with no CO date).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Fresno, CA** (n=2,000)
- Script: `agent/scripts/data_repair_ca_fresno.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/fresno_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `tasks_full` | 1,616 | Accela tasks + inspections / fees_details / conditions / related_records |
| `tasks_basic` | 384 | Accela tasks present, without inspections/fees blocks |

Both schemas share the same status/date repair logic. Top-level date sources are `DATA.date` and `search_data['Applied On']`; issuance and completion come from spaced Accela task event keys (`Marked as `, ` on `).

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,470 · Active 330 · In Review 164 · Inactive 24 · missing 12

Mapping from `DATA.status` was already correct for all non-null rows (`Final Inspection Complete`/`Final CO Issued`/`Final Inspection`/`TCO Issued`→Final; `Issued`/`Approved`→Active; `Rejected`/`Reject`→Inactive; review-stage statuses→In Review).

Issues:
1. **12 blank `DATA.status` rows** (also blank `search_data.Status`) with only TBD / empty early workflow → filled as **In Review** (11) or **Active** (1: `B18-00518` has `Building Re-Review` / `Approved`).
2. **25 stale statuses** with `Inspection` / `Final Inspection Complete` (or equivalent completion) while `DATA.status` remained `Issued` (24) or `Comments Delivered` (1) → **FIXED to Final**.
3. **8 Rejected rows** also carry historical Final Inspection Complete events; status left as **Inactive** (trust Rejected), and their `FINAL_DATE` is cleared below.

**After:** Final 1,495 · Active 307 · In Review 174 · Inactive 24 · missing 0  
Flags: **FILLED 12 · FIXED 25**

### FILE_DATE

Already populated for all 2,000 rows and matches `DATA.date` / `search_data['Applied On']` at calendar-day resolution. No fills or fixes.

Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 153 missing. Where `Permit Issuance` / `Issued` exists (1,847 rows), the stored date already matches the earliest Issued event — no corrections needed.

Gaps concentrated in Active/Final Sign and Grading permits (and a few misc.) whose Accela scrape has empty or Note/TBD-only `Permit Issuance` events — not recoverable from `DATA`. In Review / Inactive missing dates are acceptable.

**After:** missing still 153. Active 303/307 (98.7%) · Final 1,463/1,495 (97.9%).  
Flags: **FILLED 0 · FIXED 0**

### FINAL_DATE

**Before:** 1,152 missing; 655 of 1,470 Final rows lacked `FINAL_DATE`; 33 non-Final rows carried a final date.

Primary bug: existing `FINAL_DATE` used the **earliest** `Final Inspection Complete` when multiple exist. True completion is the **latest**.

Repairs:
- For Final rows: prefer latest among `Inspection` / `Final Inspection Complete` and `Certificate of Occupancy` / `Final CO Issued`; fallback to `Final Inspection`, then `TCO Issued`.
- **FILL** 25 Final rows from Final CO Issued events (mostly `STATUS_ORIGINAL=final co issued` with empty Inspection TBD).
- **FIX** 300 Final rows from earliest→latest completion date.
- **CLEAR** 8 Rejected (Inactive) rows with spurious finals.
- After status promotion, Issued→Final rows keep their completion dates under Final.

**Not repairable:** ~630 Final rows have only TBD/empty Inspection events and no Certificate of Occupancy date in `DATA`.

**After:** Final 865/1,495 (57.9%) have `FINAL_DATE`; Active / In Review / Inactive have 0.  
Flags: **FILLED 25 · FIXED 308**

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 12 | 25 | 12 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 153 → 153 |
| FINAL_DATE | 25 | 308 | 1,152 → 1,135 |

Ideal coverage after repair:
- `FILE_DATE`: 100% of all rows
- `PERMIT_DATE`: 98.7% Active, 97.9% Final (remainder: no Issued event in DATA)
- `FINAL_DATE`: 57.9% Final (remainder: TBD/empty inspection workflow, no CO date); 0% on non-Final
- `STATUS_NORMALIZED`: 100% populated
