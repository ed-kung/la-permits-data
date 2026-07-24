# Monterey Park CA data repair

**Summary:** Monterey Park’s 2,000 sample records are Accela Citizen Access payloads (`date` / `status` / `tasks`, with optional `inspections` / `fees_details`). Upstream `STATUS_NORMALIZED` was often derived from stale `STATUS_ORIGINAL` while `DATA.status` had advanced (e.g. ORIGINAL=`issued` but status=`Final` / `Expired Permit`) — 25 FIXED, 3 FILLED. `FILE_DATE` already matches `DATA.date` for all rows (100%). `PERMIT_DATE` gained 211 fills (Certificate of Occupancy / temporary CO Certificate events; Approved discretionary Determination / Planning Review dates). `FINAL_DATE` gained 69 fills from Inspections/Final or Closed/Close, 4 FIXED to the last re-final event, and 1 spurious Expired Permit FINAL cleared. Script: `agent/scripts/data_repair_ca_monterey_park.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Monterey Park"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Monterey Park, CA (after Alhambra … Manhattan Beach) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `tasks_full` | 1,985 |
| `tasks_basic` | 14 |
| `tasks_contacts` | 1 |

Task event keys use leading/trailing spaces (`'Marked as '`, `' on '`), same as Downey / Inglewood.

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` |
| `FILE_DATE` | `DATA.date` (fallback `search_data.Date`) |
| `PERMIT_DATE` | Permit Issuance / Issued; fallback Certificate / Issued*; for status Approved: Determination or Planning Review / Approved |
| `FINAL_DATE` | last Inspections / Final; fallback last Closed / Close |

Status map: Final / Closed / Closed-Compliant → Final; Issued / Approved / Active / Issued Temporary / In Violation → Active; Expired Permit / Expired Plan Check / Expired / Withdrawn / Void / Revoked / Unfounded → Inactive; Pending / Plan Check / Applied / Ready to Issue / Corrections / Reported / Investigate → In Review.

## Field assessment

### STATUS_NORMALIZED — 3 missing; 25 incorrect

- Ideal values: Active, Final, In Review, Inactive.
- Root cause of incorrect values: `STATUS_NORMALIZED` tracked stale `STATUS_ORIGINAL` (often still `issued` / `pending` / `plan check`) while Accela `DATA.status` had moved to Final, Expired Permit, Approved, Issued, etc.
- Notable fixes: Active→Final (12), Active→Inactive Expired Permit (4), In Review→Active Issued/Approved (6), In Review→Final (2), plus fills for Reported→In Review (2) and Unfounded→Inactive (1).
- After repair: no missing STATUS; Final 1,002; Active 524; Inactive 258; In Review 216.

### FILE_DATE — complete and correct

- Ideal: application / submittal date for all records.
- 2,000 / 2,000 match `DATA.date` (0 mismatches, 0 missing).
- No FILLED / FIXED.

### PERMIT_DATE — correct when present; 211 fillable Active/Final gaps

- Ideal: populated for Active and Final.
- Where both `PERMIT_DATE` and Permit Issuance / Issued exist, calendar day always matches (0 mismatches) → no FIXED.
- Missing before repair: Active 220/534, Final 58/988 (plus In Review / Inactive gaps not required).
- Fill sources:
  - Certificate / Issued* for Non-Residential Certificate of Occupancy and Temporary CO (no Permit Issuance task) — 67 Issued + 3 Issued Temporary
  - Determination / Planning Review / Approved for discretionary Approved rows (yard sale, temporary sign, home occupation, etc.) — 139
  - Permit Issuance / Issued on a few Issued/Final rows whose status was previously mis-labeled In Review — 2
- Still missing after repair (no issuance/approval event in DATA):
  - Final 58 — almost all Historical Documents (`status=Closed`) with only Closed/Close
  - Active 17 — In Violation fire cases (3), Approved rows without an Approved task event (14)

After repair: Active 507/524 (96.8%), Final 944/1,002 (94.2%).

### FINAL_DATE — Final mostly correct; 69 fillable; 4 early-final; 1 spurious

- Ideal: populated for Final.
- Existing FINAL_DATE almost always matches Inspections / Final (and often Closed / Close ±1 day). Prefer the **last** Inspections/Final when a record was re-finaled.
- Missing Final before: 69/988 under old status labels; after remapping, 83 Final rows lacked FINAL — 69 fillable from Closed/Close or Inspections/Final, 14 unfillable (mostly fire-suppression Finals with AsBuilts / TBD Inspections and no Close).
- 4 Final rows used an earlier Final event while a later Final/Close exists → FIXED to the last event.
- 1 Expired Permit row carried FINAL_DATE → cleared as FIXED.

After repair: Final 988/1,002 (98.6%); Active / In Review / Inactive have none.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 3 | 25 | 3 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 211 | 0 | 576 → 365 |
| `FINAL_DATE` | 69 | 5 | 1,080 → 1,012 |

| STATUS_NORMALIZED | Before | After |
| --- | --- | --- |
| Final | 988 | 1,002 |
| Active | 534 | 524 |
| Inactive | 252 | 258 |
| In Review | 223 | 216 |
| (missing) | 3 | 0 |

## Artifacts

- Script: `agent/scripts/data_repair_ca_monterey_park.py` (`data_repair`)
- Run: `.venv/bin/python agent/scripts/data_repair_ca_monterey_park.py`
