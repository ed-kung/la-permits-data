# Pasadena CA data repair

**Summary:** Pasadena’s 1,998 sample records are Tyler EnerGov payloads (`entity` / `details` / `fees`, with optional reviews or basic key sets). `FILE_DATE` already matches `entity.ApplyDate` (UTC day) for every row. The main defects are (1) `STATUS_NORMALIZED` derived from stale `STATUS_ORIGINAL` that disagrees with `entity.CaseStatus` on 7 rows; (2) `FINAL_DATE` copied from `entity.FinalDate` on 401 non-Final cases where that field often equals `IssueDate` or `ExpireDate`, not a sign-off; (3) a few missing dates fillable after status remap. Repair fixes 7 statuses, fills 1 `PERMIT_DATE` and 4 `FINAL_DATE` values, and clears 401 spurious finals. Script: `agent/scripts/data_repair_ca_pasadena.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Pasadena"`, `STATE == "CA"` |
| N | 1,998 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Pasadena, CA (after Alhambra … Palos Verdes Estates; La Cañada Flintridge already has `data_repair_ca_la_canada_flintridge.py`) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,900 |
| `entity_fees_reviews` | 60 |
| `entity_basic` | 38 |

Canonical fields under `entity` (details used as fallback):

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate` |
| `FINAL_DATE` | `entity.FinalDate` (fallback `details.FinalizeDate`) |

`ExpireDate` is a validity window, not a completion date. On Approved / Issued / Expired permits, `FinalDate` often equals `IssueDate` or `ExpireDate` and is not a finaling date.

## Field assessment

### STATUS_NORMALIZED — 0 missing; 7 incorrect

Upstream mapped `STATUS_ORIGINAL` (lowercased portal label) → normalized status. That label disagrees with current `entity.CaseStatus` on 7 rows, so normalized status followed the stale label:

| CaseStatus | Was | Should be | n |
| --- | --- | --- | --- |
| Finaled | Active (`STATUS_ORIGINAL=issued`) | Final | 4 |
| Expired | Active (`STATUS_ORIGINAL=issued`) | Inactive | 1 |
| Issued | In Review (`STATUS_ORIGINAL=incomplete`) | Active | 1 |
| In Review | Inactive (`STATUS_ORIGINAL=expired`) | In Review | 1 |

Status map used: Finaled/Complete/Closed → Final; Approved/Issued/Issued - Online → Active; Expired/Canceled/Voided → Inactive; Received*/In Review/Incomplete/Pending/Open/Hold → In Review.

One edge case keeps CaseStatus over PermitStatus: `CaseStatus=Issued` with `PermitStatus=Finaled` and a `FinalizeDate` but null `entity.FinalDate` (MEC2023-01400) remains Active, matching the Glendale CaseStatus-first convention.

### FILE_DATE — complete and correct

No missing values. All 1,998 rows match the UTC calendar day of `entity.ApplyDate`. No FILLED/FIXED.

### PERMIT_DATE — mostly correct; 1 fillable after status fix

| Status (pre-repair) | Missing | Notes |
| --- | --- | --- |
| Active | 17 | Almost all `IssueDate` null (`Issued=False`) — unfillable |
| Final | 43 | Closed / Complete / Finaled legacy with null `IssueDate` — unfillable |
| In Review | 68 | Expected for pre-issuance; 1 Issued-mislabeled row becomes Active and gets filled |
| Inactive | 131 | Optional |

Where both `PERMIT_DATE` and `IssueDate` exist, UTC day always matches (0 mismatches). Repair **FILLED 1** from `IssueDate` after Issued→Active. Remaining Active/Final gaps (~59 after remap) have no issuance date in DATA; `FILE_DATE` is not used as a proxy.

### FINAL_DATE — 31 Final still empty; 401 spurious on non-Final

| Issue | n | Action |
| --- | --- | --- |
| Non-Final with `FINAL_DATE` (= `entity.FinalDate`) | 401 | Clear (FIXED). Mostly Approved×253, Issued×118, Expired×25, plus a few Canceled/Received |
| CaseStatus Finaled (mislabeled Active) with `FinalDate` but null `FINAL_DATE` | 4 | Status FIXED to Final; FINAL_DATE FILLED from `FinalDate` |
| Final rows with null `FinalDate` / `FinalizeDate` | 31 | Unfillable (Closed×13, Finaled×10, Complete×8) |

After repair, non-Final statuses have no `FINAL_DATE`; 881 / 912 Final rows have one (96.6%).

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 0 | 7 | 0 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 1 | 0 | 259 → 258 |
| `FINAL_DATE` | 4 | 401 | 720 → 1,117 |

`FINAL_DATE` missing count rises because 401 incorrect non-Final values are cleared; among Final rows, missing falls from 31 to 31 pre-remap plus fills on the 4 remapped Finaled rows (881 present after).

### Coverage after repair

| Status | n | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- |
| Active | 549 | 532 (96.9%) | 0 (0%) |
| Final | 912 | 869 (95.3%) | 881 (96.6%) |
| In Review | 70 | 2 (2.9%) | 0 (0%) |
| Inactive | 467 | 337 (72.2%) | 0 (0%) |

## Artifacts

- Script: `agent/scripts/data_repair_ca_pasadena.py` (`data_repair`)
- Run: `.venv/bin/python agent/scripts/data_repair_ca_pasadena.py`
