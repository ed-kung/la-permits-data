# Kerrville (TX) data repair

**Summary:** Kerrville was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. Its DATA column is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus`, `DateCreated`, `DateIssued`, etc.), same family as Jonestown. Of 2,000 sample rows, STATUS_NORMALIZED and FILE_DATE are already correct (0 FILLED / 0 FIXED). PERMIT_DATE and FINAL_DATE remain universally missing — `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`, and DATA has no finaling timestamp.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in sample order. Existing TX scripts covered through Kendall County / La Marque / Lago Vista / Manor / Nacogdoches / Odessa / Portland / Seagoville and earlier cities; **Kerrville, TX** was the first missing (`agent/scripts/tx/data_repair_tx_kerrville.py`).

## DATA schema

Every record is a flat MGO dict with `ProjectStatus` and `DateCreated`. Two key-set variants (differ only by presence of `PaymentProcessorModule`):

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| mgo_ppm | 1,980 | Includes `PaymentProcessorModule` |
| mgo_base | 20 | Same payload without that key |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | — |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel) | — (always sentinel in sample) |
| FINAL_DATE | — (none available) | — |

## Findings by field

### STATUS_NORMALIZED

Before / after: Final 1,244; Active 492; In Review 201; Inactive 63. No missing values.

`ProjectStatus` × STATUS_NORMALIZED is exact 1:1:

| ProjectStatus | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Project Closed/Complete | Final | 1,244 |
| Permit Issued | Active | 492 |
| Pending (Under Review) | In Review | 190 |
| Stop Work Order | In Review | 11 |
| Project Closed/Permit Expired | Inactive | 58 |
| Withdrawn | Inactive | 5 |

STATUS_ORIGINAL matches `ProjectStatus` (case/whitespace normalized) on every row. **FILLED 0, FIXED 0.** Repair encodes the map (including Kerrville-specific `Project Closed/Permit Expired` → Inactive) for future drift.

### FILE_DATE

Fully populated (0 missing). Every row equals `DateCreated` at calendar-day resolution. **FILLED 0, FIXED 0.** Ideal coverage: application/submittal date present for all records.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (parsed as missing). No other issuance/approval timestamp exists in DATA. Ideal rule would fill Active (492) and Final (1,244) rows; **none can be filled from this payload.** **FILLED 0, FIXED 0.**

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated`, `ScheduledDueDate`, and power-request dates are empty or sentinel. No finaled / completion / CO / sign-off field. Ideal rule would fill Final (1,244) rows; **none can be filled.** **FILLED 0, FIXED 0.**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Post-repair coverage by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- |
| Active (492) | 100% | 0% | — |
| Final (1,244) | 100% | 0% | 0% |
| In Review (201) | 100% | — | — |
| Inactive (63) | 100% | — | — |

Date-order violations: none (no PERMIT/FINAL dates to compare).

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_kerrville.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_tx_kerrville_repaired.parquet`
