# Temple (TX) data repair

**Summary:** Temple was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after League City). All 2,000 rows are MyGovernmentOnline (MGO) project payloads (`mgo_ppm` 1,983; `mgo_base` 17). STATUS_NORMALIZED had 1 missing value (`PERMIT APPROVED`) filled as Active; all other statuses already matched `ProjectStatus`. FILE_DATE was already complete and matched `DateCreated` on every row. PERMIT_DATE and FINAL_DATE remain fully missing: `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` on every row, and no final/sign-off timestamp exists in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Temple, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_temple.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_temple_repaired.parquet`

## DATA schema

Flat MGO project object. Two top-level key-set variants; both expose the same status and date fields:

| INFERRED_SCHEMA | n |
| --- | ---: |
| mgo_ppm | 1,983 |
| mgo_base | 17 |

Canonical source fields:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | Whitespace-stripped; Temple-specific map + heuristics |
| FILE_DATE | `DateCreated` | Always present |
| PERMIT_DATE | `DateIssued` | Always sentinel in sample → unfillable |
| FINAL_DATE | (none) | No final/CO/completion timestamp in payload |

`mgo_ppm` differs from `mgo_base` only by the presence of `PaymentProcessorModule` (`MGO`).

## Field assessment

### STATUS_NORMALIZED

1 missing, 0 incorrect before repair.

**Missing (FILLED 1):**

| ProjectStatus | Corrected | n |
| --- | --- | ---: |
| PERMIT APPROVED | Active | 1 |

Root cause: original normalization left `STATUS_ORIGINAL` = `permit approved` unmapped. Portal text is an issued/approved state parallel to `APPROVED` / `PERMIT ISSUED`.

All other 1,999 rows already matched the intended `ProjectStatus` → STATUS_NORMALIZED mapping (including `Closed - Incomplete` → Inactive and `Approved with Conditions` → In Review).

After repair: Active 257, Final 1,349, In Review 148, Inactive 246; 0 nulls.

### FILE_DATE

Fully populated (0 missing). Every row matches `DateCreated` at calendar-day resolution (0 FILLED, 0 FIXED). Ideal: populated for all records — met.

### PERMIT_DATE

2,000 / 2,000 missing before and after (0 FILLED, 0 FIXED).

`DateIssued` is `0001-01-01T00:00:00` on every sample row (MGO / .NET empty-date sentinel). No alternate issuance timestamp exists in DATA (`ScheduledDueDate`, power-request dates, etc. are null). Ideal: populated for Active and Final — **not met** (0% for both); not repairable from this payload.

### FINAL_DATE

2,000 / 2,000 missing before and after (0 FILLED, 0 FIXED).

`DateUpdated` is also the sentinel on every row; no completion / final inspection / CO date field is present. Ideal: populated for Final — **not met** (0%); not repairable from this payload. No spurious non-Final FINAL_DATE values to clear.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1 | 0 | 1 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Coverage after repair:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 257 | 100% | 0% | 0% |
| Final | 1,349 | 100% | 0% | 0% |
| In Review | 148 | 100% | 0% | 0% |
| Inactive | 246 | 100% | 0% | 0% |

Date-order violations: none (no PERMIT_DATE / FINAL_DATE values to compare).

## Conclusion

Temple’s MGO extract supports reliable status repair and FILE_DATE validation, but does not expose usable issuance or final dates in this sample. The repair script fills the one unmapped Active status and is ready to apply real `DateIssued` values if a future extract stops using the .NET sentinel.
