# Hermosa Beach CA data repair

**Summary:** Hermosa Beach’s 2,000 sample records are Accela Citizen Access scrapes (`tasks` workflow events plus `status` / `date`). `FILE_DATE` is already complete and matches `DATA.date`. Material repairs: fill 18 missing `STATUS_NORMALIZED` values from uncommon Accela statuses; fill 16 missing `PERMIT_DATE` values from alternate issuance/approval events; fill 4 missing `FINAL_DATE` values from `Closed / Closed`; correct 2 Final rows whose `FINAL_DATE` used `Finaled - C of O` instead of `Inspections / Finaled`; clear 8 spurious `FINAL_DATE` values on non-Final rows. ~206 Historical Building Record stubs have empty `tasks` and remain unfillable for permit/final dates. Script: `agent/scripts/data_repair_ca_hermosa_beach.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Hermosa Beach"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Hermosa Beach, CA (after Alhambra … Hawthorne) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `tasks` | 1,999 |
| `search_data_only` | 1 |

Canonical fields from the Accela `tasks` schema:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` |
| `FILE_DATE` | `DATA.date` (fallback `Application Submittal / Applied`) |
| `PERMIT_DATE` | `Permit Issuance / Issued` (fallbacks below) |
| `FINAL_DATE` | `Inspections / Finaled` (then `Finaled - C of O`, `Closed / Closed`, `Certificate of Occupancy / Final CO Issued`) |

PERMIT_DATE fallbacks when `Permit Issuance / Issued` is absent: `Permit Application In Review / Issued`; OTC `Application Submittal / Approved - No PC Required`; for `Approved` revisions only, `Final Building Review / Approved`.

Status map: Finaled / Finaled - Complete → Final; Issued / Approved / Inspections → Active; EXPIRED / Expired Permit / Expired Plan / Void / Withdrawn / Denied → Inactive; Applied / Ready to Issue / In Review / In Plan Review / Pending / PREZONE / INQUIRY / CONCURNT → In Review.

## Field assessment

### STATUS_NORMALIZED — 19 missing; 0 incorrect among present

Upstream mapping from `STATUS_ORIGINAL` already matches `DATA.status` wherever both are set. Gaps are uncommon Accela labels that were never normalized:

| DATA.status | Expected | n | Flag |
| --- | --- | --- | --- |
| Finaled - Complete | Final | 8 | FILLED |
| PREZONE | In Review | 4 | FILLED |
| INQUIRY | In Review | 3 | FILLED |
| Expired Plan | Inactive | 2 | FILLED |
| CONCURNT | In Review | 1 | FILLED |

One `search_data_only` Solar stub (`25TMP-000067`) has blank `Status` → remains missing.

After repair: Final 1,528; Active 193; Inactive 164; In Review 114; missing 1.

### FILE_DATE — complete and correct

- Ideal: application / submittal date for all records.
- 2,000 / 2,000 populated; 1,999 / 1,999 full-schema rows match `DATA.date` calendar day.
- `Application Submittal / Applied` differs from `DATA.date` on 63 rows (often a later day); upstream correctly used `DATA.date` as the open/file date — left as-is.
- No FILLED / FIXED.

### PERMIT_DATE — correct when present; 16 fillable; many historical stubs unfillable

- Ideal: populated for Active and Final.
- Where both `PERMIT_DATE` and `Permit Issuance / Issued` exist (1,448 Active/Final rows), calendar day always matches (0 mismatches).
- Pre-repair missing on Active/Final: 264 (Active 24, Final 240). Of those, 206 Finaled rows are Historical Building Record migrations with empty `tasks` — no issuance event in DATA.
- Fillable from alternate events (**FILLED 16**):
  - Active / approved (Revision BLD): 10 from `Final Building Review / Approved`
  - Active / issued: 2 from `Permit Application In Review / Issued`
  - Final / finaled: 4 from `Permit Application In Review / Issued` or OTC `Approved - No PC Required`

After repair: Active 181/193 (93.8%), Final 1,292/1,528 (84.6%). Remaining Active/Final gaps are mostly empty-task historical stubs.

### FINAL_DATE — mostly correct; 4 fillable; 2 wrong; 8 spurious on non-Final

- Ideal: populated for Final.
- Pre-repair: Final missing 217/1,520; of those with a workflow finaling event, almost all already matched `Inspections / Finaled`.
- **FIXED 2** Final rows: `FINAL_DATE` equaled `Inspections / Finaled - C of O` while a later `Inspections / Finaled` existed → overwritten to Finaled.
- **FILLED 4** Final rows from `Closed / Closed` (no Inspections finaling event).
- **FIXED 8** non-Final rows with spurious `FINAL_DATE` (Issued×4 still open in Accela with `Closed=TBD` or lagged status; EXPIRED×2; Void×1; Ready to Issue×1) → cleared. Accela `DATA.status` remains authoritative (not remapped to Final solely from inspection events).
- ~213 Final rows (mostly Historical Building Record) have no finaling event → stay missing.

After repair: Final 1,315/1,528 (86.1%); Active / In Review / Inactive have none.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 18 | 0 | 19 → 1 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 16 | 0 | 422 → 406 |
| `FINAL_DATE` | 4 | 10 | 681 → 685 |

Missing `FINAL_DATE` rises slightly because 8 non-Final spurious values are cleared (+8) while only 4 Final gaps are filled (−4); among Final rows, coverage improves (1,303 → 1,315 with dates, including 8 newly Final `Finaled - Complete` rows that already had dates).

| STATUS_NORMALIZED | Before | After |
| --- | --- | --- |
| Final | 1,520 | 1,528 |
| Active | 193 | 193 |
| Inactive | 162 | 164 |
| In Review | 106 | 114 |
| (missing) | 19 | 1 |

## Artifacts

| Path | Role |
| --- | --- |
| `agent/scripts/data_repair_ca_hermosa_beach.py` | `data_repair()` implementation + CLI |
| `AGENT_DATA_PATH/processed_data/permits_ca_hermosa_beach_repaired.parquet` | Repaired sample output |
