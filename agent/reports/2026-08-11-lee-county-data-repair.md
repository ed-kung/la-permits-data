# Lee County (FL) data repair

Summary: Lee County was the first FL sample jurisdiction without a repair script after Jacksonville. Accela Civic Access payloads expose status and workflow dates under `DATA.status` and task events. The repair remaps 101 statuses from the live Accela status (4 FILLED, 97 FIXED), corrects 447 `PERMIT_DATE` values that had been set to the certificate date instead of Permit Issuance Issued, and recovers 40 `FINAL_DATE` values from certificate / cert-of-use events. Remaining Active/Final date gaps are almost entirely legacy `tasks_shell` conversion records with empty workflow histories.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Lee County, FL** (Jacksonville already has a script)
- Sample size: **2,005** records

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `tasks_shell` | 1,217 | Accela tasks present but no dated events (mostly `Closed-Conversion`) |
| `tasks_full` | 665 | `inspections` + `fees_details` + dated task events |
| `tasks_contacts` | 92 | `contacts` present, no `inspections`, dated events |
| `tasks_basic` | 31 | Dated events without the full inspections/fees bundle |

Canonical field sources:

- `DATA.status` → `STATUS_NORMALIZED`
- `DATA.date` (when date-like) → `FILE_DATE`
- Earliest Permit Issuance / Issued → `PERMIT_DATE`
- Latest Certificate Issuance Cert of Compliance / Occupancy / Partial CC Issued, else Inspections Certificate of Use Issued → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,693; Inactive 126; Active 102; In Review 80; missing 4.
- Missing statuses: `Closed-TMP` (2), `Resubmitted-In Review` (1), `Pending Inspections` (1) — all fillable from `DATA.status`.
- `STATUS_ORIGINAL` often lags the Accela payload (64 rows). Examples: ORIG=`permit issued` while `DATA.status`=`Closed-CC Issued` / `Permit Expired`; ORIG=`in review` while Accela already shows `Permit Issued` or `Closed-CO Issued`.
- Upstream mapping errors corrected using `DATA.status`:
  - `Closed-Cert of Use Issued` / `Closed-PCC Issued` were Active → **Final**
  - `Closed-Administrative` / `Closed-Not Effective` / `Closed-Old` were Final → **Inactive**
  - Stale Active / In Review rows whose Accela status is Closed-CC/CO Issued, Permit Expired, Withdrawn, etc. → remapped
- After repair: Final 1,701; Inactive 172; Active 75; In Review 57; **0 missing**. Every row matches `_map_status(DATA.status)`.

### FILE_DATE

- Before: 1 missing (`COM199803838`). `DATA.date` holds the record ID string, not a calendar date, and Application task events are empty → **not fillable**.
- All other 2,004 rows already matched `DATA.date` at day resolution (0 FIXED).

### PERMIT_DATE

- Before: 1,423 missing. Among rows with a Permit Issuance / Issued event, **425** existing `PERMIT_DATE` values matched the certificate date instead of Issued (upstream copied final into permit).
- Repair: **19 FILLED** (Active/Final with Issued but null permit); **425 FIXED** to Issued; **22 FIXED** cleared to null where `PERMIT_DATE` equaled the certificate date and no Issued event existed.
- After repair: Active **73/75 (97.3%)**; Final **455/1,701 (26.7%)**. The 2 Active gaps are `Pending Inspections` with no Issued event (correctly still missing). Final gaps are concentrated in `tasks_shell` (0/1,173) where Accela has no issuance history.

### FINAL_DATE

- Before: 1,558 missing; among status=Final, 1,247/1,693 missing. Existing finals usually matched Certificate Issuance, except **3** rows that used Inspections Completed one day earlier than Cert of Compliance Issued.
- Repair: **37 FILLED** (including rows promoted to Final after status fix); **3 FIXED** to the certificate date. Spurious finals on non-Final rows cleared when status remaps away from Final.
- After repair: Final **484/1,701 (28.5%)** overall; **406/441 (92.1%)** on `tasks_full`. All `tasks_shell` Final rows remain without `FINAL_DATE` (no certificate events in DATA).

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_lee_county.py` (`data_repair`)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 4 | 97 | 4 | 0 |
| FILE_DATE | 0 | 0 | 1 | 1 |
| PERMIT_DATE | 19 | 447 | 1,423 | 1,426 |
| FINAL_DATE | 37 | 3 | 1,558 | 1,521 |

`PERMIT_DATE` missing rises by 3 because 22 incorrect certificate-copied values were cleared and only 19 new Issued dates were filled (net −3 populated, but fewer *wrong* values).

## Not repairable from DATA

- `tasks_shell` Closed-Conversion / Closed-Completed style rows: empty task events → no `PERMIT_DATE` or `FINAL_DATE`.
- `COM199803838`: `DATA.date` is a record ID; no Application event date → `FILE_DATE` stays missing.
- Active `Pending Inspections` without Permit Issuance / Issued → `PERMIT_DATE` stays missing by design.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_lee_county.py`
- No derived parquet written; run the script’s `__main__` block for live stats.
