# Coconut Creek (FL) data repair

Assessed Coconut Creek permits in `permits_fl_sample.parquet` (2,001 rows) — the first `(JURISDICTION, STATE)` pair without an existing `agent/scripts/{state}/data_repair_*.py` script. Wrote `agent/scripts/fl/data_repair_fl_coconut_creek.py` to repair `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the raw `DATA` JSON.

## DATA schema

Every row has a nested `Permit` object with `Status`, `Applied Date`, `Issued Date`, and `C.O. Issued`. Optional companions (`Fee`, `Inspection`, `Review`, …) define key-set variants. `INFERRED_SCHEMA` prefixes:

| Prefix | n (sample) |
| --- | --- |
| `portal_fee_insp` | 945 |
| `portal_fee` | 880 |
| `portal_insp` | 83 |
| `portal_basic` | 93 |

Suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) reflect which of Applied / Issued / C.O. dates are present.

Canonical mappings:

- `Permit.Status` (+ `Issued Date` for Open) → `STATUS_NORMALIZED`
- `Permit['Applied Date']` → `FILE_DATE`
- `Permit['Issued Date']` → `PERMIT_DATE`
- `Permit['C.O. Issued']`, else Passed (`Status=P`) final-ish inspection → `FINAL_DATE`

## Field assessment

### STATUS_NORMALIZED

`Permit.Status` mirrors `STATUS_ORIGINAL` 1:1 (`Closed`/`Open`/`Void`/`Expired`/`Reject`). Upstream mapping treated all `Open` as `In Review`, including 76 rows that already have an `Issued Date`. Those are issued but not yet closed and should be `Active`. `Closed`→`Final` and `Void`/`Expired`/`Reject`→`Inactive` were already correct. No null statuses.

### FILE_DATE

Populated for all 2,001 rows and matches `Applied Date` on every record. No repairs needed.

### PERMIT_DATE

Matches `Issued Date` whenever present (1,889 rows). Missing where `Issued Date` is blank: 56 pre-issuance Open (`In Review`), 49 Inactive, and 7 Final (`G-FEES` / `T-REMOVAL` fee or tree-removal cases with no issuance stamp). After reclassifying Open+issued to Active, all Active rows have `PERMIT_DATE`. No incorrect values to overwrite.

### FINAL_DATE

Matches `C.O. Issued` when present (1,091 rows). 692 Final (`Closed`) rows lack `C.O. Issued`; 72 of those have a Passed final-ish inspection (`FINAL STRUCTURAL`, `ROOF FINAL`, `FINAL ELECTRIC`, etc.) usable as a completion date. One Inactive (`Void`) row carried a spurious `FINAL_DATE` from `C.O. Issued` and was cleared. Remaining ~620 Final rows have neither CO nor a Passed final inspection in `DATA`.

## Repair performance

| Field | FILLED | FIXED |
| --- | --- | --- |
| `STATUS_NORMALIZED` | 0 | 76 |
| `FILE_DATE` | 0 | 0 |
| `PERMIT_DATE` | 0 | 0 |
| `FINAL_DATE` | 72 | 1 |

Status counts after repair: Final 1,782 · Active 76 · Inactive 87 · In Review 56.

Missing dates after repair:

| Status | n | FILE missing | PERMIT missing | FINAL missing |
| --- | --- | --- | --- | --- |
| Active | 76 | 0 | 0 | 76 (expected) |
| Final | 1,782 | 0 | 7 | 620 |
| In Review | 56 | 0 | 56 (expected) | 56 (expected) |
| Inactive | 87 | 0 | 49 | 87 |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_coconut_creek.py` (`data_repair`)
