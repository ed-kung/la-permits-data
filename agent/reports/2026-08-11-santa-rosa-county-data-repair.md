**Summary:** First FL sample jurisdiction without an existing repair script (after Ocala in list order) was **Santa Rosa County**. DATA is a single MyGovernmentOnline (MGO) project family (`ProjectStatus` / `DateCreated` / `DateIssued`, all 2,000 rows). STATUS_NORMALIZED was already populated for every row; 7 `Administratively Closed` rows labeled Final were FIXED to Inactive. FILE_DATE was already complete and matched `DateCreated`. `DateIssued` is always the `.NET` sentinel `0001-01-01`, and no completion/CO date field exists, so PERMIT_DATE and FINAL_DATE remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selected

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Santa Rosa County, FL** → `agent/scripts/fl/data_repair_fl_santa_rosa_county.py` (2,000 sample rows).

## DATA schema

All 2,000 rows share one flat MGO key set (`PaymentProcessorModule=MGO`). Content variants recorded in `INFERRED_SCHEMA`:

| Schema         | Rows  |
| -------------- | ----: |
| `mgo_modern`   | 1,577 |
| `mgo_imported` |   423 |

`mgo_imported` is identified by `TypeList` containing `Imported Fee`. No nested inspections/fees objects; no varying top-level key sets.

Canonical fields:

| Target field      | Source in DATA                                      |
| ----------------- | --------------------------------------------------- |
| STATUS_NORMALIZED | `ProjectStatus` (whitespace-stripped)               |
| FILE_DATE         | `DateCreated`                                       |
| PERMIT_DATE       | `DateIssued` when not `0001-01-01` (never in sample) |
| FINAL_DATE        | *(none)*                                            |

`STATUS_ORIGINAL` matches live `ProjectStatus` on all 2,000 rows (case-normalized).

## Field assessments

### STATUS_NORMALIZED

Upstream map was already correct for 1,993 / 2,000 rows:

| ProjectStatus            | Upstream STATUS_NORMALIZED | Assessment |
| ------------------------ | -------------------------- | ---------- |
| Closed/Complete (1,863)  | Final                      | Correct    |
| Active (103)             | Active                     | Correct    |
| Pending (Under Review) (25) | In Review               | Correct    |
| Expired (2)              | Inactive                   | Correct    |
| Administratively Closed (7) | Final                   | Incorrect → Inactive |

All 7 `Administratively Closed` rows are legacy `Imported Fee` shells with sentinel `DateIssued` and no completion stamp. They are closed without a true final/sign-off, so they are remapped to Inactive (consistent with Riverside County / San Luis Obispo County treatment of administrative close).

**Repair:** 0 FILLED, 7 FIXED. Missing after: 0.

### FILE_DATE

Already populated on all 2,000 rows; calendar day matches `DateCreated` for every row.

**Repair:** 0 FILLED, 0 FIXED. Missing after: 0.

### PERMIT_DATE

Missing on all 2,000 rows (including all 103 Active and 1,863 Final). Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row. `DateUpdated` and scheduled/power-request dates are likewise null/sentinel.

**Repair:** 0 FILLED, 0 FIXED (script will fill from a real `DateIssued` if present in future extracts). Missing after: 2,000. Active/Final coverage: 0%.

### FINAL_DATE

Missing on all 2,000 rows. Payload has no finaled / completion / CO timestamp.

**Repair:** 0 FILLED, 0 FIXED. Missing after: 2,000. Final coverage: 0%.

## Repair performance (sample)

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | -----: | ----: | -------------: | ------------: |
| STATUS_NORMALIZED |      0 |     7 |              0 |             0 |
| FILE_DATE         |      0 |     0 |              0 |             0 |
| PERMIT_DATE       |      0 |     0 |          2,000 |         2,000 |
| FINAL_DATE        |      0 |     0 |          2,000 |         2,000 |

Status distribution after repair: Final 1,863; Active 103; In Review 25; Inactive 9.

Ideal date coverage after repair:

| Status    | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --------- | --------: | ----------: | ---------: |
| Active    |   100%    |         0%  |        —   |
| Final     |   100%    |         0%  |        0%  |
| In Review |   100%    |         —   |        —   |
| Inactive  |   100%    |         —   |        —   |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_santa_rosa_county.py`
- Repaired sample: `$AGENT_DATA_PATH/santa_rosa_county_repaired_sample.parquet`
