# Contra Costa County data repair

**Summary:** First CA-sample jurisdiction without an existing repair script was Contra Costa County (2,000 rows). Accela Citizen Access payloads split into `tasks_full` (1,333 with dated workflow events) and `tasks_shell` (662 legacy/converted records with empty or TBD-only task histories), plus 4 `tasks_null` and 1 `tasks_basic`. Main defects: 41 unmapped statuses (27 fillable); `Approved 5 Year Cert` miscategorized as In Review; `DATA.date` often a record ID so 801 `FILE_DATE` gaps (41 fillable from Application/Intake events); `PERMIT_DATE` already correct wherever `Permit Issuance / Issued` exists but unrecoverable on shells; `FINAL_DATE` missing on hundreds of Final rows that still have Approved Final* inspections, plus 2 stale first-Finaled dates and 2 spurious Inactive finals. Script: `agent/scripts/ca/data_repair_ca_contra_costa_county.py`. Artifact: `$AGENT_DATA_PATH/contra_costa_county_repaired_sample.parquet`.

## Sample and schemas

| INFERRED_SCHEMA | n |
| --- | ---: |
| tasks_full | 1,333 |
| tasks_shell | 662 |
| tasks_null | 4 |
| tasks_basic | 1 |

Useful fields: `DATA.status` (= `STATUS_ORIGINAL` on all 2,000 rows), `search_data['File Date']` (620 rows), `DATA.date` (date-like on only 622; otherwise a record number such as `BI326185`), workflow `tasks[].events` (HTML / NBSP-padded `updated as` + `on` keys), and `inspections[]` with `Title` / `Status` / `Status Date`.

## STATUS_NORMALIZED

Upstream coverage followed common Accela labels (`finaled`, `expired`, `issued`, …) but left workflow-stage and enforcement labels unmapped, and mistyped one approved-certificate status.

| Issue | Action |
| --- | --- |
| 27 unmapped statuses (`Plan Check Distribution Begin`, `Send Payment Email`, `Sent Rider Issuance Email`, `Official permit filed`, `PC ONLY`, `Revision Needed`, …) | FILLED → In Review (or Final / Inactive for `Closed - Code Enforcement` / `Ent. Dec. Withdrawn` / `Recorded Lien`) |
| 9 `Approved 5 Year Cert` (RRIP) labeled In Review | FIXED → Active |
| 14 blank `DATA.status` (no `search_data.Status`) | left null |

**Repair:** FILLED 27, FIXED 9. Missing 41 → 14.

After repair: Final 1,191, Inactive 432, In Review 191, Active 172, null 14.

`Approved OTC` rows correctly stay In Review: their `Permit Issuance` workflow is still at `Send Payment Email` / `Pending`, not `Issued`.

## FILE_DATE

Ideal: populated for all records. When both the column and a DATA source exist they always match at calendar-day resolution (1,199 / 1,199). Gaps are concentrated on `tasks_shell` rows where `DATA.date` stores the Accela record ID.

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 41 | earliest dated `Application Submittal` / `Intake Submittal` / `Intake Completed` / `Initialized` event |
| FIXED | 0 | — |

Remaining missing after repair: **760** (no date-like `DATA.date`, no `search_data['File Date']`, no dated application/intake events).

Coverage after repair: 1,240 / 2,000 (62.0%).

## PERMIT_DATE

Ideal: present for Active and Final. Where a `Permit Issuance / Issued` event exists, current `PERMIT_DATE` already matches (968 / 968). No alternate issuance field appears in DATA for rows without that event.

| Repair | n |
| --- | ---: |
| FILLED | 0 |
| FIXED | 0 |

Remaining Active/Final missing `PERMIT_DATE` after repair: **47 Active + 503 Final** — overwhelmingly converted `Finaled` / `Completed` / `Closed` / `OWN OCCU` shells and a handful of `Issued` rows whose task history never recorded a dated Issued mark.

Coverage after repair: Active 125/172 (72.7%), Final 688/1,191 (57.8%).

## FINAL_DATE

Ideal: present for Final. Existing finals usually matched the first `Inspections / Finaled` mark; two rows needed the later Finaled date. Hundreds of Final shells carry Approved Final* inspections (`120 Building - Final`, `520 Mechanical - Final`, etc.) with no Finaled task mark.

| Repair | n | Detail |
| --- | ---: | --- |
| FILLED | 414 | Final* titled Approved / F inspections (excludes Pre Final) |
| FIXED | 4 | 2 → latest Finaled; 2 spurious Inactive finals cleared |

Coverage after repair: Final 1,104/1,191 (92.7%); Active / In Review / Inactive all 0% (spurious finals cleared).

Remaining Final without `FINAL_DATE`: **87** (`Completed` ×43, `Finaled` ×19, `Closed` ×16, `OWN OCCU` ×7, plus 2 other) — no Finaled task event and no Approved Final* inspection.

## Performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 27 | 9 | 41 → 14 |
| FILE_DATE | 41 | 0 | 801 → 760 |
| PERMIT_DATE | 0 | 0 | 1,031 → 1,031 |
| FINAL_DATE | 414 | 4 | 1,308 → 896 |

Missing `FINAL_DATE` falls sharply because inspection Status Dates recover finals on converted records; missing `FILE_DATE` / `PERMIT_DATE` barely move because those fields were never stored in the Accela scrape for shell rows.

## Why remaining gaps persist

1. **`DATA.date` is often a record ID.** On 1,378 rows the top-level `date` field is something like `BI326185`, not an application date. Without `search_data['File Date']` or dated Application/Intake events, `FILE_DATE` cannot be recovered.
2. **Empty task histories on converted permits.** `tasks_shell` rows (and many `Completed` Permit Submittal / `OWN OCCU` / `Closed` records) have no `Permit Issuance / Issued` event, so `PERMIT_DATE` stays missing even when status is Active/Final.
3. **Final without a finaling artifact.** Remaining Final gaps lack both `Inspections / Finaled` and an Approved Final* inspection Status Date.
4. **Blank portal status.** 14 rows have null `DATA.status` and no `search_data.Status`, so `STATUS_NORMALIZED` cannot be inferred.

**Bottom line:** Contra Costa’s Accela scrape mixes modern workflows (reliable Issued / Finaled dates) with a large converted shell population where status is present but filing/issuance timestamps were never migrated. Status and final-inspection repairs close most of the actionable gaps; file and permit dates on shells are agency-side omissions rather than mapping errors.
