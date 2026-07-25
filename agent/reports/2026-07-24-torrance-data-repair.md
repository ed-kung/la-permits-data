# Torrance CA data repair

**Summary:** Torrance’s 2,001 sample records are Accela Citizen Access payloads (`tasks` / `status` / `date` / `inspections` / `fees_details`). The dominant defect is **Archiving misclassified as In Review** (758 rows) — Archiving is the Accela close-out status after finaling and should be Final. Secondary issues: Final Routing* should be Active (post-issuance inspection), stale `STATUS_ORIGINAL` vs `DATA.status`, blank statuses, a handful of missing `PERMIT_DATE` values, and `FINAL_DATE` values that track Final Routing instead of Inspection / Finaled (or appear on non-Final rows). Script: `agent/scripts/data_repair_ca_torrance.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Torrance"`, `STATE == "CA"` |
| N | 2,001 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Torrance, CA (after Alhambra … South El Monte) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `tasks_full` | 2,000 |
| `tasks_null` | 1 |

Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` |
| `FILE_DATE` | `DATA.date` (fallback `search_data['Created Date']`) |
| `PERMIT_DATE` | `Permit Issuance` / `Issued` (fallback `Revision Issued`) |
| `FINAL_DATE` | latest `Inspection` / `Finaled` (fallback `Closed` or `Close File` / `Finaled`) |

`DATA.status` is authoritative over `STATUS_ORIGINAL` (23 casefold mismatches where original is stale). Final Routing / Archiving dates are not used as completion dates.

Status map: Final / Finaled / Archiving → Final; Issued / Approved / Final Routing / Final Routing Complete → Active; Expired / Withdrawn / Cancelled → Inactive; Received* / In Review / Submitted / Out for Corrections / Corrections Needed / Ready to Issue / In Process → In Review.

## Field assessment

### STATUS_NORMALIZED — 4 missing; 783 incorrect

| Issue | n | Repair |
| --- | --- | --- |
| Archiving → In Review (should be Final) | 758 | FIXED |
| Final Routing / Final Routing Complete → In Review (should be Active) | 12 | FIXED |
| DATA.status=Finaled but STATUS was Active/In Review | 8 | FIXED |
| Other stale STATUS_ORIGINAL vs DATA.status | 5 | FIXED |
| Blank `DATA.status` (ELE/PLM with only TBD Application Submittal) | 4 | FILLED → In Review |

After repair, every row matches the map above from `DATA.status` (0 mismatches). Distribution shifts from In Review–heavy (857) to Final-heavy (1,359), as expected once Archiving is corrected.

### FILE_DATE — complete and correct

- Ideal: application / submittal date for all records.
- 2,001 / 2,001 match the calendar day of `DATA.date` (0 mismatches, 0 missing).
- No FILLED / FIXED.

### PERMIT_DATE — correct when present; Active gaps only on Approved

- Ideal: populated for Active and Final.
- Where both `PERMIT_DATE` and `Permit Issuance / Issued` exist, day matches for 1,832 rows (first Issued). Two Archiving rows used `Revision Issued` only → FILLED via that fallback.
- Missing before → after: 167 → 165.
- After repair: Final 1,355 / 1,359 (99.7%); Active 436 / 475 (91.8%).
- All 39 Active gaps are `Approved` (29 Underground Utility Waiver + trade permits) with no Issued event — unfillable.
- 4 Archiving Final rows (utility waivers) also lack Issued → left missing.
- 1 `tasks_null` Archiving row keeps its existing dates (no workflow to validate).

### FINAL_DATE — Final rows mostly recoverable; routing dates corrected

- Ideal: populated for Final.
- Upstream often stored the first Finaled date, or an earlier Final Routing date when Finaled came later (~72 rows).
- Repair uses **latest** `Inspection / Finaled`, else `Closed`/`Close File` / `Finaled`. Does **not** use Final Routing* or Archiving dates.
- FILLED 14 (Final rows with Finaled in DATA but null `FINAL_DATE`).
- FIXED 262: 249 date corrections + 13 clears of spurious values on non-Final rows (Final Routing* ×12, Issued ×1).
- After repair: Final 1,322 / 1,359 (97.3%); Active / In Review / Inactive have none.
- 37 Final rows remain without `FINAL_DATE`: 31 Archiving after Expired (no Finaled), 5 Archiving without Finaled/Expired events, 2 withdrawn/cancelled then archived, 1 Finaled with Inspection still TBD.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 4 | 783 | 4 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 2 | 0 | 167 → 165 |
| `FINAL_DATE` | 14 | 262 | 680 → 679 |

Missing `FINAL_DATE` is nearly flat overall because remapping Archiving→Final adds many rows that already had dates, while clearing 13 spurious non-Final values and correcting routing→Finaled dates reshuffles coverage. Among Final rows, coverage is 1,322 / 1,359 (97.3%).

| STATUS_NORMALIZED | Before | After |
| --- | --- | --- |
| Final | 593 | 1,359 |
| Active | 469 | 475 |
| In Review | 857 | 87 |
| Inactive | 78 | 80 |
| (missing) | 4 | 0 |

| STATUS_NORMALIZED | PERMIT_DATE after | FINAL_DATE after |
| --- | --- | --- |
| Active | 436 / 475 (91.8%) | 0 / 475 |
| Final | 1,355 / 1,359 (99.7%) | 1,322 / 1,359 (97.3%) |
| In Review | 0 / 87 | 0 / 87 |
| Inactive | 45 / 80 | 0 / 80 |

`FILE_DATE` after: 2,001 / 2,001 (100%).

## Artifacts

- Script: `agent/scripts/data_repair_ca_torrance.py`
- Sample output: `AGENT_DATA_PATH/torrance_repaired_sample.parquet`
