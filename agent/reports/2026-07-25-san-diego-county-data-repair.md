# San Diego County data repair

**Summary:** First CA-sample jurisdiction without an existing repair script was San Diego County (2,000 rows). Accela Citizen Access payloads are nearly uniform (`tasks_full` ×1,999, `tasks_sparse` ×1). Main defects: stale `STATUS_ORIGINAL` lagged `DATA.status` on 85 rows, producing 73 wrong `STATUS_NORMALIZED` values (notably Completed labeled Active despite Finaled inspections); 106 Active/Final rows missing `PERMIT_DATE` despite `Permit Issue Date` in `more_details`; 590+ Final rows missing `FINAL_DATE`, of which 141 were fillable from Finaled tasks, Pass FINAL inspections, or closure workflows; 1 spurious `FINAL_DATE` on Active. `FILE_DATE` already matched `DATA.date` for every row. Script: `agent/scripts/ca/data_repair_ca_san_diego_county.py`. Artifact: `$AGENT_DATA_PATH/san_diego_county_repaired_sample.parquet`.

## Sample and schemas

| INFERRED_SCHEMA | n |
| --- | ---: |
| tasks_full | 1,999 |
| tasks_sparse | 1 |

Useful fields: `DATA.status` / `search_data['Record Status']`, `DATA.date` / `search_data['Opened Date']`, `tasks` → Permit Issuance (`Issuance Complete`) and Under Construction - Inspections (`Finaled`), `more_details.Application Information.EXPIRATION['Permit Issue Date']`, inspections titled `*FINAL*` with Status `Pass` (`Status Date`). `Last Update Date` on inspections is often a 2012-11-19 Accela migration stamp and is not used.

## STATUS_NORMALIZED

Upstream normalization followed `STATUS_ORIGINAL`, which disagrees with live `DATA.status` on 85 rows (case-insensitive). That stale original status drove incorrect norms:

| Issue | Action |
| --- | --- |
| 28 `Completed` (search status Completed; most have Finaled) labeled Active | FIXED → Final |
| 15 `Issued Expired` labeled Active | FIXED → Inactive |
| 9 `Closed` labeled In Review / Active | FIXED → Final |
| 7 `Request Closed - Approved` labeled Active / In Review | FIXED → Final |
| 4 `In Violation` labeled In Review | FIXED → Active |
| 3 `Withdrawn` labeled Active | FIXED → Inactive |
| 2 `DIR Approved` / 2 `PC Approved` labeled In Review | FIXED → Active |
| 1 each: Completed→Inactive, Issued→Inactive, Issued Invalid Expired→Active | FIXED |
| 1 `Recommended` with null NORM | FILLED → In Review |

**Repair:** FILLED 1, FIXED 73. Missing 5 → 4 (four blank `DATA.status` / blank Record Status stubs remain).

After repair: Final 1,419, Inactive 236, Active 192, In Review 149, null 4.

## FILE_DATE

Already populated for all 2,000 rows and matched `DATA.date` (and `Opened Date` where present) at calendar-day resolution. No FILLED/FIXED.

## PERMIT_DATE

Ideal: present for Active and Final. Where `PERMIT_DATE` and Permit Issuance / Issuance Complete both exist they always match (1,054 / 1,054). `Permit Issue Date` in more_details agrees on almost all overlapping rows (5 day-level disagreements); Issuance Complete is treated as canonical and `Permit Issue Date` is fill-only.

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 106 | Active/Final rows with `Permit Issue Date` but no Issuance Complete / missing PERMIT_DATE |
| FIXED | 0 | — |

Remaining Active/Final missing `PERMIT_DATE` after repair: **608** (Active 82 + Final 526). Mostly Closed enforcement / citation / planning approvals and Completed stubs with neither issuance event nor Permit Issue Date.

Coverage after repair: Active 110/192 (57.3%), Final 893/1,419 (62.9%).

## FINAL_DATE

Ideal: present for Final. Existing finals always matched Under Construction - Inspections / Finaled when that event existed (783 / 783).

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 141 | Finaled task (incl. remapped Completed), Pass FINAL inspection Status Date, Case Closure / Complete, Complete / Complete, Status / Closed |
| FIXED (cleared on non-Final) | 1 | Spurious FINAL_DATE on Active |

Remaining Final without `FINAL_DATE`: **494** — overwhelmingly Closed enforcement / noise / grading shells and Completed records with empty task events and no Pass FINAL inspection (plus Request Closed - Approved, Authorized, legacy/recorded stubs).

Coverage after repair: Final 925/1,419 (65.2%); Active / In Review / Inactive all 0% (spurious final cleared).

## Performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 73 | 5 → 4 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 106 | 0 | 941 → 835 |
| FINAL_DATE | 141 | 1 | 1,215 → 1,075 |

## Why remaining gaps persist

1. **Stale shells without workflow dates.** Many Closed PDS Enforcement Complaint / General Enforcement / citation records and Completed building stubs have empty `tasks` and no inspections, so neither issuance nor finalization dates exist in DATA.
2. **Non-building terminals.** DIR/PC/ZA approvals, Request Closed - Approved, Authorized consultant listings, and RECORDED/legacy closed planning cases often reach a terminal status without Permit Issuance or Finaled inspection events.
3. **Blank status records.** Four rows have null `DATA.status` and blank `Record Status` with empty tasks — no basis to fill `STATUS_NORMALIZED`.
4. **Inspection Last Update Date is unreliable.** Prefer task Finaled `on` dates and Pass FINAL `Status Date`; do not use Last Update Date (bulk 2012-11-19 migration stamps).
