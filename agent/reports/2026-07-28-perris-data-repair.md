# Perris (CA) data repair

**Summary:** Assessed Perris's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_perris.py`. Perris uses an Accela Citizen Access portal payload. The main defect is stale `STATUS_NORMALIZED` values derived from `STATUS_ORIGINAL` while live `DATA.status` has advanced (especially Finaled still coded Active). The repair fixes 200 statuses, fills 41 PERMIT_DATEs and 188 FINAL_DATEs, clears 2 spurious FINAL_DATEs, and advances 4 FILE_DATEs to earlier Application Submittal Accepted marks. After repair, FILE_DATE is 100% populated, Final has 99.3% FINAL_DATE, Active has 87.5% PERMIT_DATE, and Final has 77.6% PERMIT_DATE.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Perris, CA**.

## DATA schema

All 2,000 rows have DATA. Two key-set variants (1,997 full portal shells with contacts/inspections/fees; 3 lean shells omitting those). Content-based `INFERRED_SCHEMA`:

| Schema | N | Notes |
| --- | --- | --- |
| `portal_issued_finaled` | 904 | Permit Issuance Issued + finaling evidence |
| `portal_issued` | 446 | Issued present, no finaling date |
| `portal_application_only` | 393 | Application / top-level date only |
| `portal_final_insp_only` | 257 | Final evidence present, no Issued |

Canonical mappings from DATA:

- `DATA.status` / `search_data.Status` (+ Issued workflow upgrade) → `STATUS_NORMALIZED`
- Earliest of `DATA.date` / `search_data.Date` / Application Submittal Accepted* → `FILE_DATE`
- Earliest Permit Issuance `Issued` → `PERMIT_DATE`
- Earliest Inspection `Final Inspection Complete` (fallbacks: Finaled-task `Finaled`, Final CO Issued, Pass/Passed Final* inspection) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Final 890 / Active 742 / In Review 350 / Inactive 18 / missing 0.

Root cause: `STATUS_NORMALIZED` was mapped from stale `STATUS_ORIGINAL` (search-listing snapshot, always lowercase and often behind the live portal). `DATA.status` is the current Accela case status. Examples: 125 rows with `STATUS_ORIGINAL=issued` / Active while `DATA.status=Finaled`; Issued shells still In Review; Failed/Cancelled/Expired left Active or In Review.

Repair performance: **0 FILLED, 200 FIXED**; missing after: **0**.

After: Final 1,037 / Active 618 / In Review 300 / Inactive 45.

Notable transitions: Active→Final 126, In Review→Active 25, In Review→Final 20, Active→Inactive 23, In Review→Inactive 5, Inactive→Final 1 (`failed` original with live Finaled status).

### FILE_DATE

Before: 0 missing. All 2,000 values match top-level `DATA.date` (and `search_data.Date` where present).

Four rows have an Application Submittal Accepted* mark earlier than `DATA.date`; those FILE_DATEs were brought forward.

Repair: **0 FILLED, 4 FIXED**. Coverage remains 100%.

### PERMIT_DATE

Before: 691 missing. Where both present, PERMIT_DATE matches Permit Issuance `Issued` exactly (1,309/1,309).

Repair: **41 FILLED, 0 FIXED** — Active/Final rows that gained (or already had) Issued task dates but lacked PERMIT_DATE.

Remaining Active/Final gap: **309** (mostly older Solar and Annual Fire Life and Safety shells with no Permit Issuance history). Active coverage after repair: **541 / 618 (87.5%)**; Final: **805 / 1,037 (77.6%)**.

### FINAL_DATE

Before: 1,156 missing. When both present, FINAL_DATE matches earliest `Final Inspection Complete` for nearly all rows.

Repair: **188 FILLED** (72 from Final Inspection Complete on status-promoted / previously missing Final rows; 115 from Finaled-task `Finaled`; 1 from Pass Final* inspection), **2 FIXED** (cleared spurious FINAL_DATE on Inactive Void / Expired).

Final coverage after repair: **1,030 / 1,037 (99.3%)**. Seven Finaled shells lack Final Inspection Complete, Finaled-task dates, and Final*-titled Pass inspections (Solar Pass / annual fire Pass titles are not treated as completion stamps). No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_perris.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky (Failed / Cancelled / Expired / Void / Withdrawn); Finaled / CofO Issued → Final; Issued / Permit Issued / Inspection Phase → Active; dated Permit Issuance Issued promotes In Review → Active; final-inspection evidence alone does not promote Issued → Final.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 200 | 0 | 0 |
| FILE_DATE | 0 | 4 | 0 | 0 |
| PERMIT_DATE | 41 | 0 | 691 | 650 |
| FINAL_DATE | 188 | 2 | 1,156 | 970 |

### Coverage after repair

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 541 / 618 (87.5%) | 0 / 618 (0%) |
| Final | 805 / 1,037 (77.6%) | 1,030 / 1,037 (99.3%) |
| In Review | 0 / 300 (0%) | 0 / 300 (0%) |
| Inactive | 4 / 45 (8.9%) | 0 / 45 (0%) |

FILE_DATE: 2,000 / 2,000 (100%). Chronology: 0 PERMIT &lt; FILE; 1 FINAL &lt; PERMIT.

## Artifact

- Repaired sample: `/Users/ekung/Dropbox/projects/la-permits-data-bot/repaired/permits_ca_perris_repaired.parquet`
