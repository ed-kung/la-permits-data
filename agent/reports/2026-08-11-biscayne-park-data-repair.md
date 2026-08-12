# Biscayne Park (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Belleair in sorted order) was **Biscayne Park**. DATA is a uniform CitizenServe payload (`main` / `extra` / `location`, 2,000 rows), dominated by legacy HIST imports (1,564). STATUS_NORMALIZED already matches `main.status` 1:1 (no fills/fixes). FILE_DATE was nearly always populated from `dateCreated`; **1,489** rows were FIXED (legacy ASI apply/notice dates earlier than the CitizenServe import day, plus modern `dateSubmitted` later than create) and **1** missing FILE_DATE was FILLED. PERMIT_DATE remains mostly missing: **44** FILLED from modern Code Enforcement `DATE ISSUED` / `Date Issued` (Active 15.0%, Final 0.9%). FINAL_DATE: **509** FILLED for Final rows (29.6%) from named `Final Date`, CE `Violation Resolution Date`, and Legacy CE ASI `16034` when strictly after import.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County through Belleair (with later gaps); **Biscayne Park** was the first without `agent/scripts/fl/data_repair_fl_biscayne_park.py`.

Sample size: **2,000** records.

## DATA schemas

| INFERRED_SCHEMA                 | Count |
| ------------------------------- | ----: |
| `citizenserve_legacy_code`      |   854 |
| `citizenserve_legacy_building`  |   710 |
| `citizenserve_building`         |   165 |
| `citizenserve_code`             |   136 |
| `citizenserve_other`            |    68 |
| `citizenserve_draft`            |    67 |

All rows share the same top-level envelope. Variants are content/form splits:

- `citizenserve_draft`: `main.status == 0` (unsubmitted; no `dateSubmitted`)
- `citizenserve_legacy_building` / `citizenserve_legacy_code`: HIST migrated records with unlabeled numeric ASI fields in `extra`
- `citizenserve_building` / `citizenserve_code` / `citizenserve_other`: modern named form fields

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `main.status` (`0` draft → In Review, `1` active → Active, `2` complete → Final, `-1` stopped → Inactive) |
| FILE_DATE         | Legacy Building ASI `16197`; else Legacy CE ASI `16028` when ≤ `dateCreated`; else `dateSubmitted`; else `dateCreated` |
| PERMIT_DATE       | `extra['DATE ISSUED']` / `extra['Date Issued']` (Active/Final only)         |
| FINAL_DATE        | `extra['Final Date']`; else `Violation Resolution Date` (Final); else Legacy CE ASI `16034` when after `dateCreated` (Final) |

## Field assessments

### STATUS_NORMALIZED

Before/after: Final 1,720 · Active 193 · In Review 67 · Inactive 20 · missing 0.

- Live `main.status` agrees with `STATUS_ORIGINAL` / `STATUS_NORMALIZED` on **2,000 / 2,000** rows (`draft`/`active`/`complete`/`stopped`).
- No missing or incorrect values → **FILLED 0 · FIXED 0**.

### FILE_DATE

Before: 1 missing (99.95% populated). Ideal: populated for all records.

- Upstream almost always set FILE_DATE from `main.dateCreated` (matches on 1,999 / 1,999 non-null rows).
- **1** Final building row has `dateSubmitted` but null `dateCreated` → FILE_DATE was incorrectly missing → FILLED.
- Modern non-draft rows: `dateSubmitted` falls on a later calendar day than `dateCreated` for **59** rows → FIXED to submittal date.
- Legacy Building (710): ASI `16197` is a midnight apply date matching the historical permit year (708 / 709); it precedes FILE_DATE/import on **696** rows (median gap 68 days) → FIXED. `dateCreated`/`dateSubmitted` are CitizenServe import timestamps (`16199` equals created on all 710).
- Legacy CE (854): ASI `16028` is typically the notice/incident date and precedes import on **734** rows → FIXED. Used only when ≤ `dateCreated` (53 later values left unused as ambiguous).

After: 0 missing (100%).  
Flags: **FILLED 1 · FIXED 1,489**.

| INFERRED_SCHEMA                | FIXED | FILLED |
| ------------------------------ | ----: | -----: |
| `citizenserve_legacy_code`     |   734 |      0 |
| `citizenserve_legacy_building` |   696 |      0 |
| `citizenserve_building`        |    53 |      1 |
| `citizenserve_other`           |     5 |      0 |
| `citizenserve_code`            |     1 |      0 |
| `citizenserve_draft`           |     0 |      0 |

### PERMIT_DATE

Before: 2,000 missing. Ideal: populated for Active and Final.

- No building-permit issuance key in modern `main` / named `extra`. `lastUpdatedDate` often equals submit day (weak). `expirationDate` is expiry, not issuance.
- Legacy Building ASI `16203` frequently equals the import day (`16199`/`dateCreated` on 473 / 710) → not used.
- Modern Code Enforcement exposes `DATE ISSUED` / `Date Issued` on 44 Active/Final rows → FILLED as notice issuance.

After: 1,956 missing. Coverage: Active **15.0%** (29/193); Final **0.9%** (15/1,720).  
Flags: **FILLED 44 · FIXED 0**.

### FINAL_DATE

Before: 2,000 missing. Ideal: populated for Final.

- Modern building `Final Date` present on only **2** Final rows → FILLED.
- Modern CE `Violation Resolution Date` used for Final (**28**). `Compliance Date` / `Correction/Compliance Date` appear on Active rows as deadlines → not used.
- Legacy CE ASI `16034` used for Final only when strictly after `dateCreated` (avoids import-day collapse; 374 / 854 equal created) → majority of fills.
- Legacy Building ASI `16206` is migration-clustered (many 2019–2020 dates years after the permit) → not used.

After: 1,491 missing. Final coverage **29.6%** (509/1,720).  
Flags: **FILLED 509 · FIXED 0**.

| INFERRED_SCHEMA (Final fills)  | FILLED |
| ------------------------------ | -----: |
| `citizenserve_legacy_code`     |   479 |
| `citizenserve_code`            |    28 |
| `citizenserve_building`        |     2 |

## Repair script

`agent/scripts/fl/data_repair_fl_biscayne_park.py` — `data_repair(df)`.

Performance on the 2,000-row sample:

| Field             | FILLED | FIXED | Missing before → after |
| ----------------- | -----: | ----: | ---------------------- |
| STATUS_NORMALIZED |      0 |     0 | 0 → 0                  |
| FILE_DATE         |      1 | 1,489 | 1 → 0                  |
| PERMIT_DATE       |     44 |     0 | 2,000 → 1,956          |
| FINAL_DATE        |    509 |     0 | 2,000 → 1,491          |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_biscayne_park.py`
- Repaired sample: `AGENT_DATA_PATH/biscayne_park_repaired_sample.parquet`
