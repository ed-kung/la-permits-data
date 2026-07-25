# Sacramento (city) data repair

**Summary:** First CA-sample jurisdiction without an existing repair script was Sacramento city (2,000 rows; Sacramento County already had a script). Accela Citizen Access payloads (`tasks` / `status` / `date`) are nearly uniform (`tasks_full` ×1,999, `tasks_sparse` ×1). Main defects: stale `STATUS_ORIGINAL` vs live `DATA.status` (Finaled still labeled Active, Abandoned labeled In Review, etc.); `FINAL_DATE` entirely null despite Issued / Finaled workflow events and FINAL inspections; sparse missing `PERMIT_DATE` where Ready To Issue / Issued exists. `FILE_DATE` already matched `DATA.date` for every row. Script: `agent/scripts/data_repair_ca_sacramento.py`. Artifact: `$AGENT_DATA_PATH/processed_data/permits_ca_sacramento_repaired.parquet`.

## Sample and schemas

| INFERRED_SCHEMA | n |
| --- | ---: |
| tasks_full | 1,999 |
| tasks_sparse | 1 |

Useful fields: `DATA.status`, `DATA.date` / `search_data['Date']`, workflow `tasks[].events` (`Marked as`, `on` — keys often have trailing spaces), and `inspections[].Title` / `Status Date` for legacy finals.

City Accela task names differ from Sacramento County: issuance is primarily **Ready To Issue / Issued** (not Permit Issuance), and finaling is **Issued / Finaled** (not Close Out / Inspections Complete).

## STATUS_NORMALIZED

Upstream normalization followed `STATUS_ORIGINAL`, which often lags the Accela listing status in `DATA.status`. No null statuses; 57 disagreements repaired:

| Issue | n | Action |
| --- | ---: | --- |
| `Finaled` labeled Active (ORIG=`issued`) | 28 | FIXED → Final |
| `Abandoned` labeled In Review (ORIG=`accepted` / `submittal incomplete`) | 14 | FIXED → Inactive |
| `Expired Permit` labeled Active (ORIG=`issued`) | 6 | FIXED → Inactive |
| `Estimate` labeled Final (fee-estimate-only shells) | 5 | FIXED → Inactive |
| `Finaled` labeled In Review | 3 | FIXED → Final |
| `Issued` labeled In Review | 1 | FIXED → Active |

**Repair:** FILLED 0, FIXED 57. Missing 0 → 0.

After repair: Final 1,442 / Inactive 378 / Active 98 / In Review 82.

## FILE_DATE

Already populated for all 2,000 rows and matched `DATA.date` exactly. No FILLED/FIXED.

## PERMIT_DATE

Ideal: present for Active and Final. Before repair, 800 rows lacked a permit date; where Ready To Issue / Issued* existed, current values already matched (0 mismatches).

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 21 | Earliest Ready To Issue / Ready to Issue / Issue `Issued*` (OTC `Application Submittal / Issued` fallback unused in sample fills) |
| FIXED | 0 | — |

Remaining Active/Final missing PERMIT_DATE after repair: **547** (375 Finaled + 84 Complete + 72 Closed + 12 Certificate of Occupancy + 4 Active). Skew early: ~441 of file years 2000–2006 are Finaled shells with empty task events; Complete/Closed workflows typically never record an Issued* mark.

Coverage after repair: Active 94/98 (95.9%), Final 899/1,442 (62.3%).

## FINAL_DATE

Ideal: present for Final. Every sample row had null `FINAL_DATE` before repair (2,000 / 2,000), even though modern Finaled rows carry dated Issued / Finaled events and many legacy Finaled rows retain Approved FINAL inspections.

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 1,344 | Issued\|Issue / Finaled; Ready For Pickup / Complete; else latest Approved inspection titled FINAL |
| FIXED | 0 | (no pre-existing finals to correct; no spurious non-Final finals) |

Remaining Final without FINAL_DATE: **98** — mostly Closed shells with empty workflows (65), plus Finaled (20) and Complete (13) without dated final marks or FINAL inspections.

Coverage after repair: Final 1,344/1,442 (93.2%); Active / In Review / Inactive all 0%.

## Performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 57 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 21 | 0 | 800 → 779 |
| FINAL_DATE | 1,344 | 0 | 2,000 → 656 |

## Why remaining gaps persist

1. **Legacy Accela migrations (~2000–2009).** Finaled / Closed rows often have empty or TBD-only task events. Many Finaled shells still recover FINAL_DATE from FINAL inspections; Closed shells and some Finaled rows have neither.
2. **Non-issuance workflows.** `Complete` (Ready For Pickup) and many `Closed` / certificate records never record Ready To Issue / Issued, so PERMIT_DATE cannot be recovered even when FINAL_DATE can.
3. **Status lag in upstream normalization.** Incorrect Active / In Review labels came from stale `STATUS_ORIGINAL` after Accela advanced `DATA.status` (e.g. issued → Finaled, accepted → Abandoned).

**Bottom line:** Sacramento city’s Accela scrape is the same family as Sacramento County but uses different task names. Status and FINAL_DATE are highly recoverable from live `DATA.status`, Issued / Finaled events, and FINAL inspections; remaining date gaps are mostly empty migration shells, not mapping failures.
