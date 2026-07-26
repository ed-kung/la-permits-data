# Anaheim (CA) data repair

**Summary:** Anaheim was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status is now fully populated (**FILLED 2 · FIXED 13**): stale `STATUS_ORIGINAL`-based labels were remapped from current `DATA.status` (e.g. Finaled→Active, Issued/Approved→In Review), and two null statuses were filled (Issued mark → Active; PAD → In Review). `FILE_DATE` already matched `DATA.date` / `Application Date` for all 2,002 rows (no changes). `PERMIT_DATE` missingness fell from **298 → 272** (**FILLED 26**) using `Permit Issuance` / Issued and, for Approved planning rows, `Closure` / Closed. `FINAL_DATE` missingness fell from **1,840 → 1,796** (**FILLED 44 · FIXED 3**), filling from Final Inspection Complete, Final CO Issued, Closure / Closed, and Closed - Picked Up. Remaining gaps are mostly legacy Finaled / Closed shells and Development Project Approved rows with no dated issuance or finalization events in `DATA`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Anaheim, CA** (n=2,002)
- Script: `agent/scripts/ca/data_repair_ca_anaheim.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Civic Access scrapes with top-level keys `status`, `date`, `tasks`, `more_details`, `search_data`, etc. Two rows lack `inspections` / `conditions` / `fees_details`. Sub-schemas reflect which dated workflow events are present:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks_issued` | 1,526 | `Permit Issuance` / Issued present; no finalization event |
| `accela_tasks_full` | 179 | Issued plus a finalization event |
| `accela_tasks` | 169 | Other dated task events only |
| `accela_shell` | 126 | Tasks present but no dated events |
| `accela_partial` | 2 | Missing inspections / conditions / fees_details keys |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status`; if null, task `Marked as` (Issued / Final Inspection Complete / …) |
| `FILE_DATE` | `DATA.date` (fallback: `search_data['Application Date']`) |
| `PERMIT_DATE` | `Permit Issuance` / Issued; else (Approved only) `Closure` / Closed |
| `FINAL_DATE` | `Inspection(s)` / Final Inspection Complete; `Certificate of Occupancy` / Final CO Issued; `Closure` / Closed; `Revision Status` / Closed - Picked Up |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,526 · Inactive 235 · Active 138 · In Review 101 · missing 2

Upstream `STATUS_NORMALIZED` tracks `STATUS_ORIGINAL` (portal search status), which disagrees with current `DATA.status` on 16 rows. Of those, 13 change the normalized label:

| Change | n | Cause |
| --- | ---: | --- |
| Active → Final | 9 | `DATA.status=Finaled` but search status still `issued` |
| In Review → Active | 2 | `DATA.status=Approved` vs search `in review` |
| In Review → Active | 1 | `DATA.status=Issued` vs search `ready to issue` |
| In Review → Final | 1 | `DATA.status=Closed` vs search `plan review` |
| null → Active | 1 | Empty status; tasks include `Permit Issuance` / Issued |
| null → In Review | 1 | `DATA.status=PAD` (fees / issuance pending) |

`DATA.status` → normalized map used by the repair:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled, Closed, Case Closed, Complete, Adopted | Final |
| Issued, Approved | Active |
| Plan Review, Received, In Review, Ready to Issue, On Hold, Incomplete Submittal, PAD | In Review |
| Expired, Terminated | Inactive |

**After:** Final 1,536 · Inactive 235 · Active 133 · In Review 98 · missing 0  
Flags: **FILLED 2 · FIXED 13**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA.date` (ISO date string).
- `search_data['Application Date']` matches the same calendar day for all 2,002 rows.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 298 missing (14.9%). Among Active/Final: 172 / 1,664 missing.

When present, existing `PERMIT_DATE` always matched `Permit Issuance` / Issued (1,704 / 1,704). Gaps:

1. **Approved Active** Planning and Zoning / Development Project rows with no Issued event (59 before status repair).
2. **Final** Closed / Finaled / Case Closed / Complete / Adopted shells without an Issued event (~113), often empty or near-empty task histories.
3. One **Issued** row mislabeled In Review (has Issued event but null `PERMIT_DATE`).

Repairs (Active / Final only):
1. Earliest `Permit Issuance` → Issued.
2. Else, for `DATA.status=Approved` only: latest `Closure` → Closed (planning entitlement close).

**After:** 272 missing. Filled 25 Approved Planning and Zoning + 1 Issued Building Permit.  
Remaining Active gaps: 36 Approved (23 Development Project + 13 Planning and Zoning) with no Closure / Issued dates in `DATA`.  
Flags: **FILLED 26 · FIXED 0**

Coverage after repair: Active 97/133 (72.9%) · Final 1,422/1,536 (92.6%).

### FINAL_DATE

**Before:** 1,840 missing (91.9%). Only 162 / 1,526 Final rows had a date; no non-Final rows had a spurious `FINAL_DATE`.

Existing dates almost always matched `Inspection` / Final Inspection Complete. Three disagreed with a later finalization event (Final Inspection or Final CO) by 1–several days.

Repairs for effective Final status:
1. Latest among Final Inspection Complete, Final CO Issued, Closure / Closed, Closed - Picked Up.
2. Fill when missing; overwrite when the existing value disagrees with that latest event.
3. Clear `FINAL_DATE` if status is no longer Final (none needed in this sample).

**After:** 1,796 missing. **FILLED 44** (24 Closed Plan Revision / planning, 18 Finaled including the 9 formerly Active, 2 Complete) · **FIXED 3**.  
~1,330 Final rows still lack any finalization event in `DATA` (legacy Finaled shells with only an Issued mark, or empty tasks).

Coverage after repair: Final 206/1,536 (13.4%) · Active/In Review/Inactive 0%.

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| `STATUS_NORMALIZED` | 2 | 13 | 2 | 0 |
| `FILE_DATE` | 0 | 0 | 0 | 0 |
| `PERMIT_DATE` | 26 | 0 | 298 | 272 |
| `FINAL_DATE` | 44 | 3 | 1,840 | 1,796 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_anaheim.py`
