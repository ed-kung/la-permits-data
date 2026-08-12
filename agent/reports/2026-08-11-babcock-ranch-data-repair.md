# Babcock Ranch (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Alachua County … Aventura and other already-scripted cities in list order) was **Babcock Ranch**. DATA is Accela utility-service JSON (`status` / `date` / `search_data` / `tasks` / `inspections` / `more_details`). STATUS_NORMALIZED was largely unmapped or wrong (`In Service`→Active, `Meter Removed`→In Review); all 2,000 rows are now mapped. FILE_DATE was already complete and matched Accela `date`/`search_data.Date`. PERMIT_DATE was entirely missing and is now filled for 99.3% of Active and 95.3% of Final from install-schedule / install dates. FINAL_DATE is now present for every Final row (Closure `In Service`), with incorrect finals on non-Final rows cleared and wrong finals on Final rows corrected to the Closure date.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered earlier jurisdictions (through Aventura and other later cities already scripted). **Babcock Ranch** was the first without `agent/scripts/fl/data_repair_fl_babcock_ranch.py`.

Sample size: **2,000** records (1,907 Permanent Utility Service, 93 Temporary Utility Service).

## DATA schemas

All rows share the Accela portal key set (`status`, `date`, `search_data`, `tasks`, `inspections`, `more_details`, …). Content variants by workflow richness:

| INFERRED_SCHEMA | Count |
| --------------- | ----: |
| `accela_full`   | 1,190 |
| `accela_basic`  |   809 |
| `accela_shell`  |     1 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `DATA.status` (else `search_data.Status`)                                   |
| FILE_DATE         | `search_data.Date` else `DATA.date`                                         |
| PERMIT_DATE       | Installation `Meter Install Scheduled`, else `Meter Installed`, else `more_details` Meter Install Info `Install Date` |
| FINAL_DATE        | Closure task marked `In Service`                                            |

## Field assessments

### STATUS_NORMALIZED

Before: Active 903 · In Review 31 · Inactive 2 · **missing 1,064**.

Upstream only mapped `in service`→Active, `meter removed`/`submitted`→In Review, and `withdrawn`→Inactive. Utility workflow statuses (`meter account requested`, `service account created`, `meter installed`, `connect inspections completed`, `installation scheduled`) were left null.

Corrected mapping from `DATA.status`:

| DATA.status                   | STATUS_NORMALIZED | Notes                                      |
| ----------------------------- | ----------------- | ------------------------------------------ |
| In Service                    | Final             | was Active (FIXED)                         |
| Installation Scheduled        | Active            | FILLED                                     |
| Meter Installed               | Active            | FILLED                                     |
| Connect Inspections Completed | Active            | FILLED                                     |
| Submitted                     | In Review         | already correct                            |
| Meter Account Requested       | In Review         | FILLED                                     |
| Service Account Created       | In Review         | FILLED                                     |
| Meter Removed                 | Inactive          | was In Review (FIXED)                      |
| Withdrawn                     | Inactive          | already correct                            |

After: Final 903 · In Review 776 · Active 289 · Inactive 32 · missing **0**.  
Flags: **FILLED 1,064 · FIXED 933**.

### FILE_DATE

Before/after: **0 missing**. Ideal: populated for all records.

- Upstream FILE_DATE matched `DATA.date` and `search_data.Date` on all 2,000 rows (**0** day mismatches).
- For most rows this also equals the earliest dated task event; legacy CONV rows sometimes have only a later Closure event, so Accela `date` is the right application date (not rewritten).

Flags: **FILLED 0 · FIXED 0**. Coverage: **100%** across all statuses.

### PERMIT_DATE

Before: **2,000 missing**. Ideal: populated for Active and Final.

No Accela “Permit Issuance / Issued” task exists in this utility workflow. Best issuance proxies, in order:

1. Installation → `Meter Install Scheduled` (authorization to install)
2. Installation → `Meter Installed` (implies prior authorization)
3. `more_details` Meter Install Info → `Install Date` (legacy CONV rows with sparse tasks)

After fill: Active **287 / 289 (99.3%)**; Final **861 / 903 (95.3%)**.  
Remaining gaps: **2** Active and **42** Final rows with no schedule/install signal (Closure-only conversion shells). In Review / Inactive correctly left without PERMIT_DATE.

Flags: **FILLED 1,148 · FIXED 0**.

### FINAL_DATE

Before: 1,636 missing; only 262 of 903 `In Service` rows had FINAL_DATE, and many of those matched Connection Inspections Completed / Meter Installed rather than Closure. Spurious FINAL_DATE also appeared on Connect Inspections Completed (86), Meter Installed (4), and Meter Removed (12).

- Canonical finalization: Closure task marked `In Service` (present on all 903 Final rows).
- **641** Final rows missing FINAL_DATE → **FILLED** from Closure.
- **85** Final rows with wrong FINAL_DATE (inspections/install) → **FIXED** to Closure.
- **102** non-Final rows with spurious FINAL_DATE → cleared (**FIXED**).

After: Final coverage **903 / 903 (100%)**; Active / In Review / Inactive **0** finals.  
Flags: **FILLED 641 · FIXED 187**.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_babcock_ranch.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.

## Performance (sample run)

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | -----: | ----: | -------------: | ------------: |
| STATUS_NORMALIZED |  1,064 |   933 |          1,064 |             0 |
| FILE_DATE         |      0 |     0 |              0 |             0 |
| PERMIT_DATE       |  1,148 |     0 |          2,000 |           852 |
| FINAL_DATE        |    641 |   187 |          1,636 |         1,097 |

Post-repair coverage:

- FILE_DATE: 100% all statuses
- PERMIT_DATE: Active 99.3%, Final 95.3%
- FINAL_DATE: Final 100%

## Artifacts

- Repaired sample parquet: `$AGENT_DATA_PATH/babcock_ranch_repaired_sample.parquet`
