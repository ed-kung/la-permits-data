# Altamonte Springs (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Altamonte Springs (after Alachua County). Its DATA is Tyler EnerGov JSON (`entity` / `details`). Upstream STATUS_NORMALIZED lagged CaseStatus on 9 rows and was missing on 7; FILE_DATE was already complete and correct; PERMIT_DATE gained 2 fills for Issued Actives; FINAL_DATE gained 6 fills for Finaled rows previously labeled Active and cleared 15 spurious dates on Inactive rows. Remaining Final FINAL_DATE gaps are mostly `Converted` records with no FinalDate in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County (and several later cities). **Altamonte Springs** was the first without `agent/scripts/fl/data_repair_fl_altamonte_springs.py`.

Sample size: **2,000** records.

## DATA schemas

| INFERRED_SCHEMA       | Count |
| --------------------- | ----: |
| `entity_fees`         | 1,952 |
| `entity_fees_reviews` |    48 |

Canonical source fields:

| Target field       | DATA source                                      |
| ------------------ | ------------------------------------------------ |
| STATUS_NORMALIZED  | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE          | `entity.ApplyDate` / `details.ApplyDate`         |
| PERMIT_DATE        | `entity.IssueDate` / `details.IssueDate`         |
| FINAL_DATE         | `entity.FinalDate` / `details.FinalizeDate`      |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,718 · Inactive 162 · Active 57 · In Review 56 · missing 7.

Issues:

- **Missing (7):** `In Production` (6 public-records rows) and `Voided Work Class Incorrect` (1) had no normalized status.
- **Incorrect (9):** STATUS_ORIGINAL lagged live CaseStatus — 6 `Finaled` still mapped as Active (`issued`), 1 `Closed` as In Review, 2 `Issued` as In Review.

Repair maps CaseStatus → Active / Final / In Review / Inactive (including `Converted`/`Complete`/`Finaled`/`Closed` → Final; `In Production` → In Review).

After: Final 1,725 · Inactive 163 · In Review 59 · Active 53 · missing 0.  
Flags: **FILLED 7 · FIXED 9**.

### FILE_DATE

All 2,000 rows already populated; every value matches the UTC calendar date of `ApplyDate`. No fills or fixes.

Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 178 missing. Ideal: populated for Active and Final.

- Two Issued Active rows had `IssueDate` but null PERMIT_DATE → filled (including one that also needed Active status fix).
- Remaining gaps are mostly Final shells with `Issued=False` / null IssueDate (52 public-records `Complete`, 23 `Converted`, a few `Closed`/`Finaled`) — not fillable from DATA.

After: 176 missing. Active coverage **100%**; Final **95.4%**.  
Flags: **FILLED 2 · FIXED 0**.

### FINAL_DATE

Before: 579 missing. Ideal: populated for Final.

- Six Finaled rows previously labeled Active had `FinalDate` but null FINAL_DATE → status fixed to Final and date filled.
- Fifteen Inactive (`Expired`/`Void`) rows carried FINAL_DATE from historical FinalDate stamps → cleared (FIXED), consistent with Final-only semantics.
- ~300+ Final rows (especially `Converted`) still lack FinalDate/FinalizeDate in DATA → cannot fill. ExpireDate is not used as a finalization date.

After: 588 missing (net +9 from clearing spurious Inactive dates). Final coverage **81.9%**; non-Final **0%**.  
Flags: **FILLED 6 · FIXED 15**.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_altamonte_springs.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.

## Artifacts

- Repaired sample parquet: `$AGENT_DATA_PATH/altamonte_springs_repaired_sample.parquet`
