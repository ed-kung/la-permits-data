# Daly City CA data repair

**Summary:** Daly City’s 1,999 sample records are Tyler EnerGov payloads (`entity` / `details` / `fees`, with optional reviews). `FILE_DATE` and date values that exist already match `entity.ApplyDate` / `IssueDate` / `FinalDate` (UTC day). The main defects are (1) 39 missing `STATUS_NORMALIZED` values for unmapped CaseStatus labels (Admin Final, Expired–Closed, Closeout Pending); (2) 22 incorrect statuses — Admin Closed / Superseded labeled Final despite cancelled or replaced work, Extended labeled In Review despite issuance, Stop Work Order labeled In Review; (3) 29 spurious `FINAL_DATE` values on rows remapped to Inactive. Repair fills 39 statuses, fixes 22 statuses, and clears 29 finals. Script: `agent/scripts/ca/data_repair_ca_daly_city.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` |
| Filter | `JURISDICTION == "Daly City"`, `STATE == "CA"` |
| N | 1,999 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Daly City, CA (after Newport Beach in first-appearance order) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,968 |
| `entity_fees_reviews` | 31 |

Canonical fields under `entity` (details used as fallback):

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate` |
| `FINAL_DATE` | `entity.FinalDate` (fallback `details.FinalizeDate`) |

`STATUS_ORIGINAL` matches `CaseStatus` case-insensitively on every row; gaps and errors come from the upstream normalization map, not stale portal labels. `ExpireDate` is a validity window (some rows have sentinel years like 4747), not a completion date. One Admin Closed row has `FinalDate` year 2091 — rejected by year bounds.

## Field assessment

### STATUS_NORMALIZED — 39 missing; 22 incorrect

Upstream left three CaseStatus values unmapped (NaN) and misclassified several closed/cancelled statuses as Final or In Review:

| CaseStatus | Was | Should be | n | Flag |
| --- | --- | --- | --- | --- |
| Expired–Closed | NaN | Inactive | 30 | FILLED |
| Admin Final | NaN | Final | 8 | FILLED |
| Closeout Pending | NaN | Final | 1 | FILLED |
| Admin Closed | Final | Inactive | 17 | FIXED |
| Superseded | Final | Inactive | 3 | FIXED |
| Extended | In Review | Active | 1 | FIXED |
| Stop Work Order | In Review | Inactive | 1 | FIXED |

Admin Closed descriptions confirm Inactive (expired plan check, cancelled, never picked up, no final inspection). Admin Final rows all have both `IssueDate` and a plausible `FinalDate`. Status map also covers the already-correct majority: Finaled→Final, Issued→Active, Expired/Void→Inactive, Under Review/Applied→In Review.

### FILE_DATE — complete and correct

No missing values. All 1,999 rows match the UTC calendar day of `entity.ApplyDate`. No FILLED/FIXED.

### PERMIT_DATE — correct where present; 1 Active/Final gap unfillable

Where both `PERMIT_DATE` and `IssueDate` exist, UTC day always matches (0 mismatches). Missing counts by pre-repair status: Active 0, Final 13 (mostly Admin Closed / Superseded with null IssueDate), In Review 26, Inactive 11, NaN 2.

After status remaps, Active is 50/50 and Final is 1,706/1,707. The remaining Final gap is one Finaled row (`PLMQ-9-14-39996`) with null `IssueDate` and `Issued=False` — unfillable; `FILE_DATE` is not used as a proxy. No FILLED/FIXED for this field.

### FINAL_DATE — 1 Final still empty; 29 spurious on non-Final after remap

| Issue | n | Action |
| --- | --- | --- |
| Non-Final with `FINAL_DATE` after status remap (Expired–Closed, Admin Closed, Superseded) | 29 | Clear (FIXED) |
| Finaled with null `FinalDate` / `FinalizeDate` | 1 | Unfillable |
| Admin Final / Closeout Pending (newly Final) | 9 | Already had matching `FINAL_DATE` — no fill needed |

Where both `FINAL_DATE` and `FinalDate` exist pre-repair, UTC day always matches. After repair, non-Final statuses have no `FINAL_DATE`; 1,706 / 1,707 Final rows have one (99.9%).

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 39 | 22 | 39 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 52 → 52 |
| `FINAL_DATE` | 0 | 29 | 264 → 293 |

Status distribution after repair: Final 1,707; Inactive 171; In Review 71; Active 50.

PERMIT_DATE coverage after: Active 100%; Final 99.9%. FINAL_DATE coverage after: Final 99.9%; other statuses 0%.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_daly_city.py`
- Function: `data_repair(df) -> df` with `INFERRED_SCHEMA` and `{FIELD}_FLAG` in `{"FILLED","FIXED"}`
