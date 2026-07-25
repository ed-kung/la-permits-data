# Sacramento County data repair

**Summary:** First CA-sample jurisdiction without an existing repair script was Sacramento County (2,009 rows). Accela Citizen Access payloads (`tasks` / `status` / `date`) are consistent (`tasks_full` ×2,007, `tasks_sparse` ×2). Main defects: stale `STATUS_ORIGINAL` vs `DATA.status` (plus unmapped statuses and Final Processing / Suspended remaps); `PERMIT_DATE` often set to Ready to Issue / Issued Pending Payment instead of later Issued; sparse fills from `Permit Issuance / Approved` and master-plan approval events; `FINAL_DATE` occasionally not the latest completion event, with 2 spurious non-Final finals cleared. `FILE_DATE` already matched `DATA.date` for every row. Script: `agent/scripts/data_repair_ca_sacramento_county.py`. Artifact: `$AGENT_DATA_PATH/processed_data/permits_ca_sacramento_county_repaired.parquet`.

## Sample and schemas

| INFERRED_SCHEMA | n |
| --- | ---: |
| tasks_full | 2,007 |
| tasks_sparse | 2 |

Useful fields: `DATA.status`, `DATA.date` / `search_data['Created Date']`, workflow `tasks[].events` (`Marked as`, `on` — keys often have trailing spaces).

## STATUS_NORMALIZED

Upstream normalization largely followed `STATUS_ORIGINAL`, which matches `DATA.status` on 1,991 / 2,009 rows. Gaps and errors:

| Issue | Action |
| --- | --- |
| 2 unmapped statuses (`Permit Ready Pending Payment`, `Resubmittal Uploaded`) with null NORM | FILLED → In Review |
| 24 `Final Processing` labeled Active | FIXED → Final (inspections complete, awaiting close-out) |
| 10 `Suspended` labeled In Review | FIXED → Inactive |
| 2 `VOID` labeled In Review (stale ORIG=`incomplete`) | FIXED → Inactive |
| 1 `Issued` labeled In Review | FIXED → Active |
| 1 `Completed` labeled Active | FIXED → Final |
| 9 blank `DATA.status` shells (mostly 2001–2009, empty workflow) | left missing |

**Repair:** FILLED 2, FIXED 38. Missing 11 → 9.

## FILE_DATE

Already populated for all 2,009 rows and matched `DATA.date` exactly. No FILLED/FIXED.

## PERMIT_DATE

Ideal: present for Active and Final. Before repair, 552 Active/Final rows lacked a permit date; almost none of those had an `Issued` task event (legacy Accela stubs and recent Issued rows with empty workflows).

Where an Issued* event existed, many current values equaled **Ready to Issue** or **Issued Pending Payment** rather than the later **Issued** date.

| Repair | n | Source |
| --- | ---: | --- |
| FIXED | 60 | Align to earliest Permit Issuance / Ready to Issue `Issued*` (not RTI / pending-payment) |
| FILLED | 26 | Issued* when present; else `Permit Issuance / Approved` (OTC); else `Master Plan Approved / Approved` |

Remaining Active/Final missing PERMIT_DATE after repair: **526** (skew early: ~449 of file years 2000–2006; also ~60 Issued 2022–2025 with empty task events and no dated issuance mark).

Coverage after repair: Active 135/176 (76.7%), Final 930/1,415 (65.7%).

## FINAL_DATE

Ideal: present for Final. Existing finals almost always matched an Inspection / Inspections Complete (or related) event; 39 rows matched an earlier completion when a later one existed → FIXED to latest. 4 missing Finals filled from Close Out / Inspection / Finaled / CO completion marks. 2 spurious finals cleared (Issued + Expired Non-Responsive).

| Repair | n |
| --- | ---: |
| FILLED | 4 |
| FIXED (date → latest completion) | 39 |
| FIXED (cleared on non-Final) | 2 |

Remaining Final without FINAL_DATE: **468**, overwhelmingly pre-2007 Finaled shells with empty task events and no inspections list.

Coverage after repair: Final 947/1,415 (66.9%); Active / In Review / Inactive all 0% (spurious finals cleared).

## Performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2 | 38 | 11 → 9 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 26 | 60 | 811 → 785 |
| FINAL_DATE | 4 | 41 | 1,064 → 1,062 |

## Why remaining gaps persist

1. **Legacy Accela migrations.** Finaled/Issued rows from ~2000–2006 usually have Permit Issuance / Inspection / Finaled tasks with empty or TBD-only events. Status advanced in the listing, but dated workflow was never stored.
2. **Recent Issued shells with empty events.** Dozens of 2022–2025 Issued permits show `DATA.status=Issued` but no dated Permit Issuance event (and often empty `inspections`), so no issuance date is recoverable from DATA.
3. **Blank status shells.** Nine old records have null `DATA.status`, blank search Status, and no non-TBD workflow marks.

**Bottom line:** Sacramento County’s Accela history mixes modern permits (Ready to Issue → Issued → Inspections Complete → Permit Complete) with migrated shells that only carry a coarse status. Remaining missing dates usually mean the agency never stored those events in the scrape, not that the repair mapping failed to find them.
