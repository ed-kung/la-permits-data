# St. Pete Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **St. Pete Beach**. DATA is a city permit-portal payload (`Status`, `Permit Date`, `inspections`, `fees`, …) in the same family as Daytona Beach Shores. Upstream left 558 `STATUS_NORMALIZED` nulls (blank historic Status, Online Application, ADDITIONAL DOCUMENTS NEEDED, SWO) and mapped all 284 `Open` rows to In Review instead of Active. `FILE_DATE` already matched `Permit Date` except one 1899-12-30 sentinel (cleared). `PERMIT_DATE` and `FINAL_DATE` were entirely empty; there is no issuance field in DATA, so PERMIT_DATE stays missing, while FINAL_DATE was filled on 793 Final rows from successful inspections. After repair: STATUS 92.6% (148 blank historic shells remain); FILE_DATE 99.95%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 58.6%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **St. Pete Beach, FL** → `agent/scripts/fl/data_repair_fl_st_pete_beach.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Prefix | n (approx.) | Notes |
| --- | ---: | --- |
| `historic_*` | 1,160 | `APPLICATION TYPE` / `Permit Number Old` (mostly zHistorical) |
| `portal_*` | 817 | Modern shells with `EXPIRATION DATE` / `reviews` |
| `plan_reviews_*` | 23 | `plan_reviews` instead of `reviews` |

Suffix is a slug of `DATA["Status"]` (or `blank`). Top values: `historic_closed` 569, `historic_blank` 490, `portal_closed` 433, `portal_open` 187.

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status`; blank Status + completed inspection → Final |
| FILE_DATE | `Permit Date` (application / record stamp) |
| PERMIT_DATE | *(none — do not copy Permit Date)* |
| FINAL_DATE | Latest passed final-named inspection `completed_date`; else latest any passed/complete inspection |

## Field assessments

### STATUS_NORMALIZED

| Status (DATA) | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 1,009 | Final | Correct |
| *(blank)* | 492 | **null** | Fill Final when completed insp (344); else leave null (148) |
| Open | 284 | **In Review** | Fix → Active |
| In Review | 78 | In Review | Correct |
| Online Application | 40 | **null** | Fill → In Review |
| Void | 29 | Inactive | Correct |
| ADDITIONAL DOCUMENTS NEEDED | 25 | **null** | Fill → In Review |
| Expired | 17 | Inactive | Correct |
| Withdrawn | 10 | Inactive | Correct |
| Hold | 9 | In Review | Correct |
| Cancelled | 5 | Inactive | Correct |
| SWO | 1 | **null** | Fill → Inactive |
| Abandoned | 1 | Inactive | Correct |

**Root cause:** Upstream mapped plain `STATUS_ORIGINAL` labels (`closed`→Final, `open`→In Review, `in review`→In Review, void/expired/withdrawn/cancelled→Inactive) but (1) treated Open as pre-issuance even though this portal has separate In Review / Online Application statuses, and (2) left Online Application, ADDITIONAL DOCUMENTS NEEDED, SWO, and blank historic Status unmapped.

**Repair performance:** FILLED 410, FIXED 284; missing 558 → 148. After: Final 1,353; Active 284; In Review 152; Inactive 63; null 148.

### FILE_DATE

Ideal: populated for all records.

- Before: present on **2,000 / 2,000**, but one Open row stores **1899-12-30** (invalid `Permit Date`).
- In-range `Permit Date` already matched FILE_DATE on 1,999 rows.
- **0 FILLED, 1 FIXED** (cleared the 1899 sentinel). Coverage 1,999 / 2,000 (99.95%).

### PERMIT_DATE

Ideal: populated for Active and Final.

- DATA has **no** Issued / Approved date. `Permit Date` appears on In Review / Online Application / ADDITIONAL DOCUMENTS NEEDED as well, so it is the file/application stamp, not issuance.
- Upstream PERMIT_DATE was empty for all 2,000 rows → **0 FILLED / 0 FIXED**.
- Active/Final still missing PERMIT_DATE: **1,637 / 1,637** (100%). Not repairable from DATA.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream FINAL_DATE was empty for all rows.
- **793 FILLED** from inspections: prefer latest passed/complete inspection whose type matches final/fnl/BFINAL; else latest any passed/complete `completed_date` (needed for historic `BUILDING` / `Complete -` shells without “Final” in the type name).
- Remaining Final gap: **560** — mostly Closed/historic Final shells with empty `inspections` arrays.
- Non-Final rows carry no FINAL_DATE after repair.

Coverage after repair: Final 793/1,353 (58.6%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 410 | 284 | 558 → 148 |
| FILE_DATE | 0 | 1 | 0 → 1 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 793 | 0 | 2,000 → 1,207 |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_st_pete_beach.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_st_pete_beach_repaired.parquet`

Main residual gaps: no issuance date anywhere in DATA (PERMIT_DATE), blank-Status historic shells without inspections (STATUS), and Final rows without a dated successful inspection (FINAL_DATE).
