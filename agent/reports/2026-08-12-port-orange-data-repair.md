# Port Orange (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Port Orange (2,001 rows). DATA is SmartGov portal JSON (`My Project` / `Build Status` / `Permit Inspections`), same family as Auburndale. STATUS_NORMALIZED had 127 nulls and 4 mislabels (Closed/Finaled as Active; Ready To Issue with Closed as In Review); repair FILLED 125 and FIXED 4, leaving only 2 empty shells null. FILE_DATE and PERMIT_DATE already matched `Submitted` / `Issued` when present (no date corrections). FINAL_DATE was missing on 946 Final rows with blank Closed; 645 Final dates were FILLED from Closed stamps or approved Final/COO inspections. 304 Closed Finals still lack a usable close date.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in first-appearance order. Existing FL repair scripts covered through St. Petersburg. **Port Orange** was the first without `agent/scripts/fl/data_repair_fl_port_orange.py`.

Sample size: **2,001** records.

## DATA schemas

SmartGov community portal payload. Top-level keys include `Department`, `My Project`, `Permit Type`, `Build Status`, `Permit Number`, contacts/fees/inspections arrays, and usually `Parcel Number` / `ProjectDescription`.

| INFERRED_SCHEMA    | Count |
| ------------------ | ----: |
| `smartgov_full`    | 1,798 |
| `smartgov_no_desc` |   201 |
| `smartgov_minimal` |     2 |

Canonical source fields:

| Target field      | DATA source |
| ----------------- | ----------- |
| STATUS_NORMALIZED | `Build Status` (`Closed`/`Closed/COO`/`Finaled`/`Certificate of Occupancy`→Final, `Issued`→Active, `Expired*`→Inactive, review statuses→In Review), with Closed/Issued date overrides; null Build Status inferred from My Project dates |
| FILE_DATE         | `My Project.Submitted` (else `Created`) |
| PERMIT_DATE       | `My Project.Issued` (else `Approved`) |
| FINAL_DATE        | `My Project.Closed` (else latest approved Final / Certificate of Occupancy inspection) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,654 · Inactive 185 · Active 26 · In Review 9 · missing 127.  
After: Final 1,692 · Inactive 219 · Active 54 · In Review 34 · missing 2.

- Upstream mapping covered most `Closed` / `Issued` / `Expired*` / review labels, but left **127** null (especially null Build Status and unmapped `Closed/COO`, `Additional Information Requested`, some `Expired*`).
- **Mislabels FIXED (4):**
  - 2 `Closed` + 1 `Finaled` labeled Active → Final
  - 1 `Ready To Issue` with Issued+Closed stamps labeled In Review → Final (Closed-date override)
- **Nulls FILLED (125)** from Build Status and date inference:
  - nan→Final 34 · nan→Inactive 34 · nan→Active 31 · nan→In Review 26
- Remaining **2** nulls are empty-shell records (blank `My Project`, no Build Status).

Flags: **FILLED 125 · FIXED 4**.

### FILE_DATE

Before/after: **2 missing**. Ideal: populated for all records.

- When `Submitted` is present (1,999 rows), FILE_DATE matches it exactly at day resolution.
- The 2 empty-shell rows have no Submitted/Created → cannot fill.
- No incorrect non-null FILE_DATE values found.

Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before/after: **52 missing**. Ideal: populated for Active and Final.

- When `Issued` is present (1,949 rows), upstream PERMIT_DATE matches it exactly.
- Active after repair: **54 / 54 (100%)** have PERMIT_DATE.
- Final after repair: **1,682 / 1,692 (99.4%)**; the **10** gaps are `Closed` rows with blank Issued and blank Approved.
- In Review correctly has **0** PERMIT_DATE after status overrides (Issued implies Active/Final).
- `Approved` is sometimes populated but never needed as a fallback for Active/Final gaps in this sample.

Flags: **FILLED 0 · FIXED 0**.

### FINAL_DATE

Before: **1,258 missing**. After: **613 missing** (304 of them Final). Ideal: populated for Final.

- When `Closed` is present, upstream FINAL_DATE already matched it (743/743); no FIXED needed for date values.
- Main gap: many `Closed` Finals have blank Closed (` - -`) despite status Closed.
- **645 FILLED** from Closed (including mislabeled Active→Final) or latest approved inspection whose name contains `Final` or Certificate of Occupancy / COO.
- Remaining **304** Final gaps are Closed (or Certificate of Occupancy) rows with blank Closed and no usable Final/COO inspection date.
- Non-Final statuses correctly end with FINAL_DATE null (no spurious finals retained after status fixes).

Coverage after repair: Final **1,388 / 1,692 (82.0%)**.  
Flags: **FILLED 645 · FIXED 0**.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_port_orange.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.
- Conventions aligned with `agent/scripts/fl/data_repair_fl_auburndale.py` and `agent/scripts/ny/data_repair_ny_ny.py`.

## Performance snapshot

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | -----: | ----: | -------------: | ------------: |
| STATUS_NORMALIZED |    125 |     4 |            127 |             2 |
| FILE_DATE         |      0 |     0 |              2 |             2 |
| PERMIT_DATE       |      0 |     0 |             52 |            52 |
| FINAL_DATE        |    645 |     0 |          1,258 |           613 |

Chronology after repair: **0** FILE>PERMIT inversions; **0** PERMIT>FINAL inversions.

Ideal-coverage gaps remaining: Active/Final missing PERMIT_DATE **10**; Final missing FINAL_DATE **304**; FILE_DATE missing **2**; STATUS_NORMALIZED missing **2**.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_port_orange.py`
- Repaired parquet: `AGENT_DATA_PATH/repaired/permits_fl_port_orange_repaired.parquet`
