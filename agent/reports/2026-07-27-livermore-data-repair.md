# Livermore (CA) data repair

**Summary:** Livermore was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status changes: **FILLED 3 · FIXED 5** (Ready for Coordination filled; Finaled/Expired/Issued mislabels corrected); 6 null-status shells remain unfillable. `FILE_DATE` already matched `DATA.date` for all 1,999 rows (no changes). `PERMIT_DATE` missingness fell from **1,795 → 1,190** (**FILLED 605**) using Permit Issuance / Issued and Application Intake / Issued events. `FINAL_DATE` missingness fell from **1,539 → 1,368** (**FILLED 181 · FIXED 12**), filling from Inspection Finaled and Inspection not Required, correcting two stale finals, and clearing spurious finals on non-Final rows. Remaining gaps are mostly Accela shells with empty task events.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Livermore, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_livermore.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Civic Access scrapes with top-level keys `status`, `date`, `tasks`, `more_details`, `search_data`, etc. Sub-schemas reflect which dated workflow events are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_shell` | 944 | Tasks present but no dated events |
| `accela_tasks_full` | 612 | Issued event plus Inspection Finaled / Inspection not Required |
| `accela_tasks_issued` | 243 | Issued event present; no finalization event |
| `accela_tasks` | 200 | Other dated task events only |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (fallback: non-TBD task marks) |
| `FILE_DATE` | `DATA.date` (fallback: `search_data['Date']`) |
| `PERMIT_DATE` | `Permit Issuance` / Issued\|Re-Issued; else `Application Intake` / Issued; else any Issued |
| `FINAL_DATE` | `Inspection` / Finaled; else `Inspection` / Inspection not Required (when status Finaled/Closed) |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,627 · Active 187 · Inactive 142 · In Review 34 · missing 9

Issues:
1. **5 mis-normalized rows** relative to `DATA.status`:
   - Finaled → Active (2) → Final (both have Inspection / Finaled events)
   - Expired → Active (2) → Inactive
   - Issued → In Review (1) → Active
2. **3 null `STATUS_NORMALIZED`** with `DATA.status = Ready for Coordination` (unmapped upstream) → In Review
3. **6 null `DATA.status`** shells (empty search Status, only TBD task placeholders) — not fillable

When present, `DATA.status` maps cleanly:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled, Closed | Final |
| Issued, Approved | Active |
| Applied, Pending, Plan Review, Incomplete, Out for Correction(s), Corrections Received, Ready for Coordination | In Review |
| Expired, Withdrawn | Inactive |

**After:** Final 1,629 · Active 184 · Inactive 144 · In Review 36 · missing 6  
Flags: **FILLED 3 · FIXED 5**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA.date` (string ISO date).
- `search_data['Date']` mirrors the same calendar day when present.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 1,795 missing (89.8%). Among Active/Final: 1,616 / 1,814 missing.

Root cause: upstream only populated issuance when a clear Permit Issuance event was already wired through; most over-the-counter Finaled rows carry `Application Intake` / Issued instead, and many Issued marks were never promoted into `PERMIT_DATE`.

Repairs (Active / Final only):
1. Prefer earliest `Permit Issuance` → Issued|Re-Issued.
2. Else earliest `Application Intake` → Issued|Re-Issued.
3. Else any other Issued|Re-Issued mark.

Existing non-null `PERMIT_DATE` values (204) already matched Issued events; no FIXED needed.

**After:** 1,190 missing. Active coverage 150/184 (81.5%); Final 653/1,629 (40.1%).  
Flags: **FILLED 605 · FIXED 0**

Remaining Active gaps (34): 15 Approved (fees due / Ready to Issue, no Issued mark) and 19 Issued shells or Received-only workflows with no dated Issued event.

### FINAL_DATE

**Before:** 1,539 missing (77.0%). Among Final: 1,177 / 1,627 missing. Also 10 spurious finals on non-Final rows.

Root causes:
1. Upstream populated `FINAL_DATE` only from `Inspection` / Finaled (~450 rows). Another **180** Finaled rows have `Inspection` / Inspection not Required (waived inspection) with a usable date that was ignored.
2. Two Finaled rows had `FINAL_DATE` earlier than the latest Inspection Finaled event.
3. Eight Active Issued rows and one Incomplete row had Completeness Review / Complete dates wrongly stored as `FINAL_DATE`; one Expired row retained a leftover Inspection Finaled date.

Repairs:
1. For Final status: fill/fix from Inspection / Finaled, else Inspection / Inspection not Required.
2. Clear `FINAL_DATE` when effective status is not Final.

**After:** 1,368 missing. Final coverage 631/1,629 (38.7%); no finals on other statuses.  
Flags: **FILLED 181 · FIXED 12** (2 date corrections + 10 clears)

Remaining Final gaps (~998) are mostly pre-2015 Accela shells with empty task events and no Inspection Finaled / not-Required mark.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 5 | 9 → 6 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 605 | 0 | 1,795 → 1,190 |
| FINAL_DATE | 181 | 12 | 1,539 → 1,368 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_livermore.py`
