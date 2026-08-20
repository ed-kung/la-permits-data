# Lago Vista (TX) data repair

**Summary:** Lago Vista was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. Its DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` / `mgo_base`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 2,000 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. Existing TX scripts covered through Seagoville; **Lago Vista, TX** was the first missing (`agent/scripts/tx/data_repair_tx_lago_vista.py`; index 68 of 99 jurisdictions; 2,000 sample rows).

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 1,994 | `PaymentProcessorModule == "MGO"` |
| `mgo_base` | 6 | same keys, no `PaymentProcessorModule` |

All rows have `ProjectType == "Permit"`. Content varies by `SpecificUse` (SFR, irrigation, fence, plumbing, etc.) but the date/status fields share one flat schema.

Relevant fields:

| DATA field | Role |
| --- | --- |
| `ProjectStatus` | Raw status |
| `DateCreated` | Application / create timestamp → `FILE_DATE` |
| `DateIssued` | Intended issue date → always sentinel in sample |
| `DateUpdated` | Always sentinel in sample |
| Other `*Date*` fields | Null; no CO / final / sign-off date |

## Field assessment

### STATUS_NORMALIZED

| `STATUS_ORIGINAL` | `ProjectStatus` | `STATUS_NORMALIZED` | n |
| --- | --- | --- | ---: |
| complete | Complete | Final | 1,177 |
| approved | Approved | Active | 575 |
| pending | Pending | In Review | 161 |
| expired | Expired | Inactive | 39 |
| cancelled | Cancelled | Inactive | 22 |
| withdrawn | Withdrawn | Inactive | 18 |
| never built | Never Built | Inactive | 4 |
| denied | Denied | Inactive | 3 |
| denied (fees due) | Denied (Fees Due) | Inactive | 1 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs `ProjectStatus` found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample.

Note: `ProjectStatusIsPermit` is `True` only on Approved/Active rows (575) and `False` elsewhere — a portal UI flag, not a date or status source.

### FILE_DATE

- Missing before repair: **0 / 2,000**
- Equals calendar day of `DateCreated` on every row (years 2011–2025)
- Ideal coverage (all records populated) already met

### PERMIT_DATE

- Missing before repair: **2,000 / 2,000** (including all 575 Active + 1,177 Final)
- `DateIssued` is `0001-01-01T00:00:00` on every row → treated as missing
- No other usable issue/approval timestamp in DATA (`PlacardFilename`, `ReceiptFileName` empty; no nested date structures)
- **Cannot fill** from available agency JSON; gap is a source-data limitation

### FINAL_DATE

- Missing before repair: **2,000 / 2,000** (including all 1,177 Final)
- `DateUpdated` is the same .NET sentinel; `ScheduledDueDate` and power-request dates are null
- **Cannot fill** for Final records from available agency JSON

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_lago_vista.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA` (`mgo_ppm` / `mgo_base` / `missing` / `unknown`)
- Overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED` when changed
- Status map covers Lago Vista’s `Complete`, `Approved`, `Pending`, and inactive variants (`Never Built`, `Denied (Fees Due)`, etc.)
- `PERMIT_DATE` ← real `DateIssued` when present for Active/Final
- `FINAL_DATE` cleared only if present on a non-Final row (none in sample)

## Repair performance (TX sample, n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Post-repair coverage:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- |
| Active (575) | 100% | 0% | 0% |
| Final (1,177) | 100% | 0% | 0% |
| In Review (161) | 100% | 0% | 0% |
| Inactive (87) | 100% | 0% | 0% |

Date-order violations after repair: none (no permit/final dates to compare).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → `PERMIT_DATE` stays missing.
- All Final rows lack a completion/sign-off timestamp → `FINAL_DATE` stays missing.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_lago_vista.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_tx_lago_vista_repaired.parquet`
