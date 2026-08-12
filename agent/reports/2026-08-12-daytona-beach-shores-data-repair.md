# Daytona Beach Shores (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Daytona Beach Shores was first. Its DATA is a two-schema city portal (`job` 2010–2025 vs `applicant` 1998–2013) with a rich coded `Status` field but only one usable top-level date (`Permit Date` = application/record date). Upstream left **1,952** STATUS_NORMALIZED null and left **PERMIT_DATE** / **FINAL_DATE** entirely empty. After repair: status nearly complete (FILLED 1,950 · 2 blank-Status shells remain); FILE_DATE unchanged and already correct vs Permit Date; PERMIT_DATE unrecoverable (no issuance field); FINAL_DATE FILLED **410** from successful final-close inspections.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Daytona Beach Shores, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_daytona_beach_shores.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_daytona_beach_shores_repaired.parquet`

## DATA schema

| Family | n | Notes |
| --- | ---: | --- |
| `job_*` | 1,279 | `Job Cost` / `Site Address` / `Expiration Date` (mostly 2010–2025) |
| `applicant_*` | 721 | `Applicant Name` / `Application Expiration` / `Permit Expiration` (mostly 1998–2013; 5 sentinel 2099 dates) |

INFERRED_SCHEMA is `{family}_{status_slug}` (e.g. `job_5b_closed_final_inspection_approved`, `applicant_final_approved_permit_closed`).

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Status` (coded workflow labels) |
| FILE_DATE | `Permit Date` (application / record date — present on Never Issued / Incomplete / Under Review) |
| PERMIT_DATE | *(none in DATA)* |
| FINAL_DATE | Latest inspection with Final Approved / Approved Final / Permit Closed status (`completed_date`, else `scheduled_date`) |

## Field assessments

### STATUS_NORMALIZED

**1,952 missing** before repair — upstream only mapped a few plain STATUS_ORIGINAL values (`closed` → Final, `denied`/`expired`/`withdrawn` → Inactive, `approved` → Active). Coded labels such as `(5b) Closed, Final Inspection Approved`, `Final Approved, Permit Closed`, `(4) Permit Issued`, `(2a) Under Review` were left null.

Mapping used:

| STATUS_NORMALIZED | Example `Status` values |
| --- | --- |
| Final | `(5b) Closed, Final Inspection Approved`, `Final Approved, Permit Closed`, `closed` / `closed.` |
| Active | `(4) Permit Issued`, `Permit issued, work underway`, `(4b2) Permit Re-Issued`, `Permit Printed, Waiting for Pick` |
| In Review | `(2a) Under Review`, `(1a) Application Incomplete`, `(3a)/(3b)` pre-issuance, site-plan review |
| Inactive | `Denied*`, `Expired`, `Withdrawn*`, `Permit Application Closed, Never Issued`, `Permit Closed Administratively` |

The 48 pre-populated rows already matched this map (**0 FIXED**). **1,950 FILLED.** Remaining null: **2** blank-`Status` applicant shells (one with Permit Date 2099, one with 2005 and no other status signal).

After: Final 1,711; Active 118; Inactive 102; In Review 67; null 2.

### FILE_DATE

Ideal: populated for all records.

- When Permit Date is in-range (1,995 rows), FILE_DATE already equals it (**0 FIXED / 0 FILLED**).
- **5 missing** are all `applicant` rows with Permit Date year **2099** (rejected as implausible) → cannot fill.
- Coverage after repair: Active 98.3%; Final 99.9%; In Review / Inactive 100%.

### PERMIT_DATE

Ideal: populated for Active and Final.

- DATA has **no** issued / approved date field. `Permit Date` is the file/application stamp (present on Never Issued and Incomplete), so it must not be copied into PERMIT_DATE.
- Upstream PERMIT_DATE was already empty for all 2,000 rows → **0 FILLED / 0 FIXED**.
- Active/Final still missing PERMIT_DATE: **1,829 / 1,829** (100%). Not repairable from DATA.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream FINAL_DATE was empty for all rows.
- **410 FILLED** from inspections with close language (`Approved Final - Permit Closed`, `Final Approved, Permit Closed`), using `completed_date` when present else `scheduled_date`, plus 19 legacy shells whose type/status are `Scheduled/Completed Date: …` and notes say `Final`.
- Remaining Final gap: **1,301** — mostly empty `inspections` arrays; a smaller set has inspections without close language (e.g. `Approved, okay until next inspec`, inspector name only).
- Non-Final rows carry no FINAL_DATE after repair.

Coverage after repair: Final 410/1,711 (24.0%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1,950 | 0 | 1,952 → 2 |
| FILE_DATE | 0 | 0 | 5 → 5 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 410 | 0 | 2,000 → 1,590 |

Main residual gaps: no issuance date anywhere in DATA (PERMIT_DATE), and Final rows without a dated close inspection (FINAL_DATE).
