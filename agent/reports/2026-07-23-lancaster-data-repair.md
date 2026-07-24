# Lancaster data repair — field assessment

**Summary:** Lancaster’s 2,000 sample records are almost entirely Accela `tasks` schema (1,997), plus 3 `search_data_only` listing rows with empty Status. `FILE_DATE` is complete and correct. The main fixable issues are 44 unmapped/blank statuses (especially `Final Inspection Completed` → Final) and 30 spurious `FINAL_DATE`s on non-Final Issued / Ready-to-Issue rows. Missing `PERMIT_DATE` is mostly a 2005–2009 Accela migration gap (empty workflows + bogus 01/09/2016 fee dates); only 2 specialty Active rows have usable approval proxies. Repair script: `agent/scripts/lancaster_data_repair.py`.

## Data source

- Input: `MY_DATA_PATH/processed_data/permits_la_sample.parquet`
- Filter: `JURISDICTION == "Lancaster"` (n=2,000)
- Schemas:
  - `tasks` (1,997): Accela Citizen Access (`date`, `status`, `tasks`, `search_data`, …). Event keys use unspaced names (`Marked as`, `on`).
  - `search_data_only` (3): only `search_data` with empty `Status` (temp residential records).

## Field assessment

### STATUS_NORMALIZED

| Issue | Count | Cause |
| --- | --- | --- |
| Missing (`tasks`) | 44 | Unmapped `DATA.status` values + 4 blank statuses |
| Missing (`search_data_only`) | 3 | Empty `search_data.Status`; unfillable |
| Incorrect | 0 | All previously mapped statuses already match `DATA.status` |

Missing → fill mapping:

| Raw `DATA.status` | Normalized | n |
| --- | --- | --- |
| Final Inspection Completed | Final | 29 |
| Preliminary Review | In Review | 6 |
| Approve(d) on Another Record | Inactive | 4 |
| 1st Plan Check Out | In Review | 1 |
| (blank, tasks schema) | In Review | 4 |

Existing mappings already correct for Finaled / Closed - Complete → Final; Issued / Approved / Construction / Inspection Phase → Active; Expired / Denied / Void / Abandoned / Permit Not Required → Inactive; Submitted / Plan Review / Ready to Issue / Stop Work / etc. → In Review.

### FILE_DATE

- Missing: 0 / 2,000
- For all 1,997 `tasks` rows, `FILE_DATE` equals `DATA.date`
- For 3 `search_data_only` rows, `FILE_DATE` equals `search_data["Submission Date"]`
- **No repair needed**

### PERMIT_DATE

| Status (before) | Present | Notes |
| --- | --- | --- |
| Active | 334 / 339 (98.5%) | 5 missing issuance events |
| Final | 497 / 1,214 (41%) | 717 Finaled lack Issued events |
| In Review | 0 / 222 | Expected |
| Inactive | 49 / 178 | Optional |

**Primary source:** `Permit Issuance` → `Issued` matches existing `PERMIT_DATE` for all 909 rows that have the event (0 mismatches).

**Why ~720 Active/Final dates stay missing — proxy hunt:**

| Cohort | n | What’s in `DATA` | Proxy verdict |
| --- | --- | --- | --- |
| Legacy Finaled (FILE 2005–2009) | 708 | Empty task events; fees almost all stamped `01/09/2016` (Accela conversion date, not issuance); empty inspections / attachments / `more_details` | **Unfillable** — no real approval or issuance date survives migration |
| Recent Finaled Fire Sprinklers (2024–25) | 9 | Fee date ≈ `FILE_DATE`; only `Final Inspection Complete`; Application Submittal still `TBD` (no Accepted) | **Not used** — among Fire Sprinklers *with* `PERMIT_DATE`, fee/`FILE` equals PERMIT only 11/51 (median lag 3 days); true issuance is `Permit Issuance / Issued`, often same day as `Accepted - Plan Review Not Req` |
| Active legacy Issued (2005–08) | 3 | Same empty workflow as legacy Finaled | **Unfillable** |
| Active Geotech `Approved` | 1 | `Engineering Review / Approved` on 2022-05-09; no Permit Issuance task | **FILLED** from approval date (report-style record; approval is the terminal action) |
| Active Impact Fee Credit `Issued` | 1 | `Senior Analyst Review / Accepted` on FILE_DATE | **FILLED** from Accepted (OTC-like) |

Other candidates rejected:
- `fees_details[].Date` — equals PERMIT for only 83/446 Finaled-with-PERMIT; on legacy miss rows it is the 2016 migration stamp.
- `Plans Coordination / Ready to Issue` — equals PERMIT for 251/296 when present, but **never present** on the missing-PERMIT cohort.
- `conditions.Add Date` — tracks finaling (322/431 match `FINAL_DATE`), not issuance.
- Using `FILE_DATE` as OTC proxy — PERMIT equals FILE for only 230/909 overall; unsafe for Finaled legacy / Fire Sprinklers without an Accepted/Issued event.

**Repair:** 2 FILLED via approval proxies; remaining Active gap is 3 legacy Issued rows; Final coverage unchanged at 526/1,243 after status repair.

### FINAL_DATE

| Status (before) | Present | Notes |
| --- | --- | --- |
| Final | 501 / 1,214 (41%) | 713 Finaled have no finaling events in `DATA` |
| Active | 29 / 339 | Spurious; sourced from `Final Inspection` while status remains Issued |
| In Review | 1 / 222 | Spurious Ready to Issue with `Final Inspection Complete` |
| (null status) | 29 / 47 | `Final Inspection Completed` rows; become Final after repair |

**Sources / causes:**
1. `Inspection` → `Final Inspection Complete` matches existing FINAL for all 398 Final rows that have it.
2. `Inspection` → `Final Inspection` matches the other 103 Finaled rows that only have that event (kept).
3. 29 Active Encroachment (Utilities/General/Sewer) rows have `Final Inspection` but `DATA.status=Issued` (one later Reissued) — FINAL was incorrectly set → **cleared**.
4. 1 Ready to Issue row has `Final Inspection Complete` → cleared once status stays In Review.
5. 713 Finaled rows have empty inspections and no finaling task events — **unfillable**.

## Repair results (`data_repair`)

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 44 | 0 | 47 → 3 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 2 | 0 | 1,091 → 1,089 |
| FINAL_DATE | 0 | 30 | 1,440 → 1,470 |

Missing `FINAL_DATE` rises because 30 spurious non-Final dates were cleared; Final coverage rises to 530 / 1,243 (42.6%) after reclassifying `Final Inspection Completed`.

### After-repair coverage (ideal fields)

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active (339) | 336 / 339 (99.1%) | 0 / 339 |
| Final (1,243) | 526 / 1,243 (42.3%) | 530 / 1,243 (42.6%) |
| In Review (233) | 0 / 233 | 0 / 233 |
| Inactive (182) | 49 / 182 | 0 / 182 |

## Artifacts

- Repair function: `agent/scripts/lancaster_data_repair.py` (`data_repair`)
- No derived datasets written under `AGENT_DATA_PATH`
