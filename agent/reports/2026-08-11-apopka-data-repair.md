# Apopka (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Alachua County, Altamonte Springs, and Anna Maria) was Apopka. Its DATA is CitizenServe-style JSON (`main` / `extra` / `location`). STATUS_NORMALIZED already matched `main.status` on every row. FILE_DATE was incorrectly taken from `dateCreated` on 71 rows where `dateSubmitted` falls on a later day — those were FIXED. PERMIT_DATE and FINAL_DATE are universally missing and cannot be filled from DATA (no issuance or finaling timestamps). Five Inactive BTR shells remain without FILE_DATE.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County, Altamonte Springs, and Anna Maria. **Apopka** was the first without `agent/scripts/fl/data_repair_fl_apopka.py`.

Sample size: **1,999** records.

## DATA schemas

All rows share top-level keys `main`, `extra`, `location`. Content variants:

| INFERRED_SCHEMA               | Count |
| ----------------------------- | ----: |
| `citizenserve_historical`     | 1,215 |
| `citizenserve_btr`            |   292 |
| `citizenserve_building`       |   271 |
| `citizenserve_draft`          |   108 |
| `citizenserve_contractor_reg` |    79 |
| `citizenserve_planning`       |    34 |

Canonical source fields:

| Target field      | DATA source                                                      |
| ----------------- | ---------------------------------------------------------------- |
| STATUS_NORMALIZED | `main.status` (0→In Review, 1→Active, 2→Final, -1→Inactive)      |
| FILE_DATE         | `main.dateSubmitted` (else `dateCreated` / `Application Date`) |
| PERMIT_DATE       | *(none reliable)*                                                |
| FINAL_DATE        | *(none reliable)*                                                |

## Field assessments

### STATUS_NORMALIZED

Before/after: Final 1,116 · Active 490 · In Review 242 · Inactive 151 · missing 0.

- Maps 1:1 from `STATUS_ORIGINAL` (`complete`/`active`/`draft`/`stopped`) and from `main.status` (2/1/0/-1).
- `extra.Status` is noisy (blank/None on many rows; Inactive BTRs often labeled `Completed`) and was not used to override the portal lifecycle code.

Flags: **FILLED 0 · FIXED 0**.

### FILE_DATE

Before: 5 missing. Ideal: populated for all records.

- Upstream FILE_DATE matched `main.dateCreated` on 1,994 / 1,999 rows.
- On **71** rows, `dateSubmitted` is a later calendar day than `dateCreated` (1–316 days later); FILE_DATE incorrectly retained the create day → **FIXED** to `dateSubmitted`.
- **5** Inactive BTR shells (`BTR-*`) have null `dateCreated`, `dateSubmitted`, and `Application Date` → cannot fill.

After: 5 missing. Coverage: Active/Final/In Review **100%**; Inactive **96.7%**.  
Flags: **FILLED 0 · FIXED 71**.

### PERMIT_DATE

Before/after: **1,999 missing** (0% of Active/Final). Ideal: populated for Active and Final.

Investigated candidates and rejected them:

- `extra['Issue Date']` — key present on 48 rows, always blank.
- `extra['BTR Effective Date']` — fiscal/license period start (typically Oct 1), often before the application date on renewals; not an issuance timestamp.
- `main.expirationDate` / `main.lastUpdatedDate` — validity window / last edit; not approval dates.
- `extra['Date']` — usually equals application date; when it differs it aligns with later edits, not issuance.

Flags: **FILLED 0 · FIXED 0**. Not repairable from DATA.

### FINAL_DATE

Before/after: **1,999 missing** (0% of Final). Ideal: populated for Final.

No completion / finaled / signoff / CO date exists in `main` or `extra`. Historical (`HIST-`) rows have `formComplete=False` and never set `lastUpdatedDate`. Using `lastUpdatedDate` as a final proxy would mislabel later administrative edits.

Flags: **FILLED 0 · FIXED 0**. Not repairable from DATA.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_apopka.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.

## Performance summary

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | -----: | ----: | -------------: | ------------: |
| STATUS_NORMALIZED |      0 |     0 |              0 |             0 |
| FILE_DATE         |      0 |    71 |              5 |             5 |
| PERMIT_DATE       |      0 |     0 |          1,999 |         1,999 |
| FINAL_DATE        |      0 |     0 |          1,999 |         1,999 |

## Artifacts

- Repaired sample parquet: `$AGENT_DATA_PATH/apopka_repaired_sample.parquet`
