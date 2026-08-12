# Belleair (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Bay Harbor Islands in sorted order) was **Belleair**. DATA is a uniform CitizenServe payload (`main` / `extra` / `location`, 2,000 rows). STATUS_NORMALIZED already matches `main.status` 1:1 (no fills/fixes). FILE_DATE was always populated from `dateCreated`; **263** rows were FIXED to prefer `dateSubmitted` when it falls on a later calendar day. PERMIT_DATE and FINAL_DATE are universally missing and have no reliable source in DATA, so they remain null (0% Active/Final PERMIT_DATE; 0% Final FINAL_DATE).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County through Bay Harbor Islands; **Belleair** was the first without `agent/scripts/fl/data_repair_fl_belleair.py`.

Sample size: **2,000** records.

## DATA schemas

| INFERRED_SCHEMA         | Count |
| ----------------------- | ----: |
| `citizenserve_draft`    | 1,049 |
| `citizenserve_building` |   947 |
| `citizenserve_planning` |     4 |

All rows share the same top-level envelope. Variants are content/form splits:

- `citizenserve_draft`: `main.status == 0` (unsubmitted; no `dateSubmitted`)
- `citizenserve_building`: Building Permit (non-draft)
- `citizenserve_planning`: Variance Application (non-draft)

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `main.status` (`0` draft → In Review, `1` active → Active, `2` complete → Final, `-1` stopped → Inactive) |
| FILE_DATE         | `main.dateSubmitted` else `main.dateCreated` else `extra['Date of Application']` |
| PERMIT_DATE       | *(none reliable)*                                                           |
| FINAL_DATE        | *(none reliable)*                                                           |

## Field assessments

### STATUS_NORMALIZED

Before/after: In Review 1,049 · Final 630 · Active 301 · Inactive 20 · missing 0.

- Live `main.status` agrees with `STATUS_ORIGINAL` / `STATUS_NORMALIZED` on **2,000 / 2,000** rows.
- No missing or incorrect values → **FILLED 0 · FIXED 0**.

### FILE_DATE

Before: 0 missing (100% populated). Ideal: populated for all records.

- Upstream always set FILE_DATE from `main.dateCreated` (matches on all 2,000 rows).
- For submitted records, `dateSubmitted` is the better application/submittal date. It differs from `dateCreated` on a later calendar day for **263** rows (167 Final, 88 Active, 8 Inactive; median gap 5 days, max 280).
- Drafts (1,049) have no `dateSubmitted`; keeping `dateCreated` is correct.
- `extra['Date of Application']` appears on only 4 variance rows and is redundant or wrong (one `10/24/1942`); not needed when `dateSubmitted` / `dateCreated` exist.

After: 0 missing (100%).  
Flags: **FILLED 0 · FIXED 263**.

### PERMIT_DATE

Before: 2,000 missing. Ideal: populated for Active and Final.

- No issuance / approval date key in `main` or `extra`.
- `lastUpdatedDate` is not a safe proxy (Active: often equals submit day; Final: median 36 days after submit but also tracks later edits).
- `expirationDate` is a permit expiry, not issuance.

After: 2,000 missing. Coverage: Active **0%** (0/301); Final **0%** (0/630).  
Flags: **FILLED 0 · FIXED 0**.

### FINAL_DATE

Before: 2,000 missing. Ideal: populated for Final.

- No completion / finaled / certificate / signoff timestamp in DATA.
- Cannot recover FINAL_DATE for the 630 Final (`complete`) rows from this payload.

After: 2,000 missing. Final coverage **0%** (0/630).  
Flags: **FILLED 0 · FIXED 0**.

## Repair script

`agent/scripts/fl/data_repair_fl_belleair.py` — `data_repair(df)`.

Performance on the 2,000-row sample:

| Field             | FILLED | FIXED | Missing before → after |
| ----------------- | -----: | ----: | ---------------------- |
| STATUS_NORMALIZED |      0 |     0 | 0 → 0                  |
| FILE_DATE         |      0 |   263 | 0 → 0                  |
| PERMIT_DATE       |      0 |     0 | 2,000 → 2,000          |
| FINAL_DATE        |      0 |     0 | 2,000 → 2,000          |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_belleair.py`
- Repaired sample: `AGENT_DATA_PATH/belleair_repaired_sample.parquet`
