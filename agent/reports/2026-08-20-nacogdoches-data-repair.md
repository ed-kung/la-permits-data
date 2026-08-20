# Nacogdoches (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Nacogdoches was first. Its DATA is a uniform MyGovernmentOnline (`mgo_ppm`) payload. `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 2,000 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Nacogdoches, TX** (index 58 of 99 jurisdictions; 2,000 sample rows).

## DATA schema

All 2,000 rows share one top-level key set (MGO project object). Every row includes `PaymentProcessorModule == "MGO"` → inferred schema `mgo_ppm`.

Relevant fields:

| DATA field | Role |
| --- | --- |
| `ProjectStatus` | Raw status (`Permit Issued`, `Pending`, `Closed`, `Withdrawn`) |
| `DateCreated` | Application / create timestamp → `FILE_DATE` |
| `DateIssued` | Intended issue date → always sentinel in sample |
| `DateUpdated` | Always sentinel in sample |
| Other `*Date*` fields | Null / sentinel; no CO / final / sign-off date |

## Field assessment

### STATUS_NORMALIZED

| `STATUS_ORIGINAL` | `ProjectStatus` | `STATUS_NORMALIZED` | n |
| --- | --- | --- | ---: |
| permit issued | Permit Issued | Active | 1,627 |
| pending | Pending | In Review | 207 |
| closed | Closed | Final | 165 |
| withdrawn | Withdrawn | Inactive | 1 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs `ProjectStatus` found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample.

### FILE_DATE

- Missing before repair: **0 / 2,000**
- Equals calendar day of `DateCreated` on every row
- Ideal coverage (all records populated) already met

### PERMIT_DATE

- Missing before repair: **2,000 / 2,000**
- Ideal: populated for Active (1,627) and Final (165)
- Cause: `DateIssued` is `0001-01-01T00:00:00` on **every** row (MGO/.NET empty-date sentinel). No alternate issue timestamp exists in DATA.
- **Cannot fill** from available DATA.

### FINAL_DATE

- Missing before repair: **2,000 / 2,000**
- Ideal: populated for Final (165)
- Cause: no finaled / completion / certificate-of-occupancy date in the payload; `DateUpdated` is also always the sentinel.
- **Cannot fill** from available DATA.

## Repair script

Path: `agent/scripts/tx/data_repair_tx_nacogdoches.py`

- Function: `data_repair(df)`
- Overwrites incorrect / missing target fields when DATA supports it
- Flags: `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`}
- Adds `INFERRED_SCHEMA` (`mgo_ppm` / `mgo_base` / `missing` / `unknown`)
- Status map + heuristics cover observed Nacogdoches values and common MGO variants
- `DateCreated` → `FILE_DATE`; real `DateIssued` → `PERMIT_DATE` for Active/Final; clears stray `FINAL_DATE` on non-Final rows

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Post-repair coverage:

- Active: FILE 100%, PERMIT 0%, FINAL 0%
- Final: FILE 100%, PERMIT 0%, FINAL 0%
- In Review / Inactive: FILE 100%; PERMIT/FINAL appropriately empty
- Date-order violations: none
- Schema: `mgo_ppm` = 2,000

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_nacogdoches.py`
- Repaired parquet: `AGENT_DATA_PATH/repaired/permits_tx_nacogdoches_repaired.parquet`
