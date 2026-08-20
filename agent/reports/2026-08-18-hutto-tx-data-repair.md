# Hutto (TX) data repair

**Summary:** Hutto was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows). DATA is a flat MyGovernmentOnline (MGO) payload with two key-set variants (`mgo_ppm` / `mgo_base`). STATUS_NORMALIZED already matches `ProjectStatus` 1:1 (Closed→Final, Issued→Active, Pending→In Review). FILE_DATE matches `DateCreated` on every row at calendar-day resolution. PERMIT_DATE and FINAL_DATE are missing on all rows and cannot be filled: `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01T00:00:00` everywhere, and no final/CO timestamp exists in DATA. The repair script records `INFERRED_SCHEMA` and is ready to fill/fix dates if real values appear in future extracts; on this sample it changes zero field values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sample order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover prior cities through Helotes / Houston / Hurst. **Hutto** was the first missing pair → `agent/scripts/tx/data_repair_tx_hutto.py`.

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,999 | Flat MGO project keys + `PaymentProcessorModule=MGO` |
| `mgo_base` | 1 | Same keys without `PaymentProcessorModule` |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | Closed / Issued / Pending in sample |
| FILE_DATE | `DateCreated` | Always present |
| PERMIT_DATE | `DateIssued` | Always .NET sentinel in sample → unusable |
| FINAL_DATE | — | No finaled / completion / CO field in payload |

## Field assessment

### STATUS_NORMALIZED

Before/after: Final 1,579 / Active 400 / In Review 21 / missing 0.

| ProjectStatus | ProjectStatusID | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | ---: | --- | --- | ---: |
| Closed | 743 | closed | Final | 1,579 |
| Issued | 742 | issued | Active | 400 |
| Pending | 741 | pending | In Review | 21 |

No missing or incorrect values relative to `ProjectStatus`. No FILLED/FIXED changes.

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution. Upstream stores a truncated (midnight) timestamp while DATA retains wall-clock time; day equality is treated as correct. No FILLED/FIXED changes.

### PERMIT_DATE

Missing on all 2,000 rows, including all 400 Active and 1,579 Final records where issuance should ideally be present.

`DateIssued` is `0001-01-01T00:00:00` on every sample row (MGO / .NET empty-date sentinel). No other issuance field exists in DATA. Gap is a portal export limitation, not an upstream mapping bug. Repair leaves PERMIT_DATE null; would FILLED/FIXED from a real `DateIssued` if present in future data.

### FINAL_DATE

Missing on all 2,000 rows, including all 1,579 Final (`Closed`) records.

`DateUpdated` is also the sentinel on every row; `ScheduledDueDate`, power-request dates, and nested document lists are empty. No finaled / completion / CO timestamp is available. Repair cannot fill FINAL_DATE; clears FINAL_DATE only if a non-Final row incorrectly carries one (none in sample).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0%, Final 0% (no usable source in DATA)
- **FINAL_DATE:** Final 0% (no usable source in DATA)

Date-order violations after repair: FILE>PERMIT=0, PERMIT>FINAL=0, FILE>FINAL=0.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_hutto.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_hutto_repaired.parquet`
