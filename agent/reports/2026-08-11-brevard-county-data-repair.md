# Brevard County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Escambia County in file order) was **Brevard County**. DATA is a single Accela Citizen Access family (`status` / `search_data` / `tasks`; inspections lists empty in sample). STATUS_ORIGINAL is often stale vs live `DATA.status`; remapping filled 1 null (typo `Awaiting Clent Feedback`) and fixed 63 labels (mostly Active→Inactive Expired and Active/In Review→Final). FILE_DATE was already complete and matched `search_data.Date` / `DATA.date` on all rows. PERMIT_DATE gained **13 FILLED** from Permit Issuance `Issued` (0 date fixes). FINAL_DATE was the main date win: **48 FILLED** and **58 date FIXED** (plus 3 non-Final clears), lifting Final coverage from 79.0% to **80.6%**. After repair: STATUS missing 1 shell; FILE_DATE 100%; Active PERMIT_DATE 99.1%; Final PERMIT_DATE 80.1%; Final FINAL_DATE 80.6%; non-Final FINAL_DATE 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in file order. Existing FL repair scripts covered Jacksonville through Escambia County. **Brevard County** was the first without `agent/scripts/fl/data_repair_fl_brevard_county.py`.

Sample size: **2,000** records.

## DATA schemas

| INFERRED_SCHEMA | Count |
| --------------- | ----: |
| `accela_basic`  | 1,686 |
| `accela_shell`  |   314 |

No `accela_full` rows: every `inspections` list in the sample is empty. Variants:

- `accela_basic`: at least one dated workflow task event
- `accela_shell`: Accela envelope but no dated task events (legacy / conversion shells; many `FINALED`)

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `DATA.status` (else `search_data.Status`)                                   |
| FILE_DATE         | `search_data.Date` else `DATA.date` else earliest Application Submittal / Intake |
| PERMIT_DATE       | Earliest Permit Issuance task marked `Issued`                               |
| FINAL_DATE        | Latest of: Certificate of Occupancy issued; Building/Site/Zoning/etc. Final `Finaled`/`Final`; Inspections `Final`/`Finaled`; Closure `Final`/`Closed` |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,640 · Inactive 152 · Active 145 · In Review 61 · missing 2.

- Upstream mapping used `STATUS_ORIGINAL`, which disagrees with live `DATA.status` on **63** rows (e.g. ORIGINAL=`issued` while DATA=`Expired` or `Final`).
- **1 FILLED**: typo portal status `Awaiting Clent Feedback` (unmapped originally).
- **63 FIXED**, mainly:
  - Active → Inactive when DATA is `Expired` (25)
  - Active → Final when DATA is `Final` (19)
  - In Review → Active when DATA is `Issued` (9)
  - In Review → Final (7) / Inactive (3)
- **1** row remains missing status: Miscellaneous Master Plans shell with null `status` / empty `search_data.Status` and only a TBD task mark.

After: Final 1,666 · Inactive 180 · Active 110 · In Review 43 · missing 1.  
Flags: **FILLED 1 · FIXED 63**.

### FILE_DATE

Before: 0 missing. Ideal: populated for all records.

- FILE_DATE already matched `search_data.Date` (else `DATA.date`) on **2,000 / 2,000** rows.
- No fills or fixes required.

After: 0 missing (100%).  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 437 missing. Ideal: populated for Active and Final.

- Canonical issuance signal is Permit Issuance marked `Issued` (1,576 rows).
- Existing PERMIT_DATE already agreed with that Issued date on all overlapping rows → **0 FIXED**.
- **13 FILLED** on Active/Final rows that had an Issued event but a null PERMIT_DATE (mostly stale In Review→Active remaps plus a few Active/Final gaps).
- **332** Final rows still lack PERMIT_DATE — almost all `accela_shell` / empty Permit Issuance event lists. Not repairable from DATA.
- One `ACTIVE` row has no Issued event → Active PERMIT_DATE 109/110.

After: 424 missing. Coverage: Active **99.1%** (109/110); Final **80.1%** (1,334/1,666).  
Flags: **FILLED 13 · FIXED 0**.

### FINAL_DATE

Before: 702 missing; Final coverage 1,295/1,640 (79.0%). Ideal: populated for Final.

- Prefer the **latest** among CO issued, named `* Final` tasks, Inspections Final/Finaled, and Closure Final/Closed (taking max avoids early Inspection finals that precede CO/closure).
- **48 FILLED** on Final rows with a workflow finalization mark but null FINAL_DATE.
- **58 FIXED** date corrections — all moved later onto a later finalization mark; includes **6** rows whose prior FINAL_DATE equaled Application Submittal.
- **3 FIXED** clears of spurious FINAL_DATE on non-Final rows after status remap.
- **323** Final rows still lack FINAL_DATE (309 shells + 14 dated records with no finalization marks).

After: 657 missing. Final coverage **80.6%** (1,343/1,666). Non-Final FINAL_DATE: **0**.  
Flags: **FILLED 48 · FIXED 61**.

## Repair script

`agent/scripts/fl/data_repair_fl_brevard_county.py` — `data_repair(df)`.

Performance on the 2,000-row sample:

| Field             | FILLED | FIXED | Missing before → after |
| ----------------- | -----: | ----: | ---------------------- |
| STATUS_NORMALIZED |      1 |    63 | 2 → 1                  |
| FILE_DATE         |      0 |     0 | 0 → 0                  |
| PERMIT_DATE       |     13 |     0 | 437 → 424              |
| FINAL_DATE        |     48 |    61 | 702 → 657              |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_brevard_county.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/brevard_county_repaired_sample.parquet`
