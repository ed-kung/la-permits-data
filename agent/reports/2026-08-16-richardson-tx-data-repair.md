# Richardson (TX) data repair

**Summary:** Richardson was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Southlake). All 2,000 rows are municipal portal payloads keyed by `record_id` / `Application Data`, with an optional nested `Permit` block that is often a *different* permit at the same Location ID (only 155 rows have an aligned Permit Number). Upstream left STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE entirely null. The repair fills 1,925 statuses from Application Data (aligned Permit Status when more specific), 14 FILE_DATE values for In Review rows, 241 PERMIT_DATE values (aligned Issue Date + Active APPROVED App Date), and 1,786 FINAL_DATE values (100% of Final). 75 shell / status-less rows remain unmapped. No true apply/submittal timestamp exists for Active/Final rows, so FILE_DATE stays mostly missing.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Richardson, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_richardson.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_richardson_repaired.parquet`

## DATA schema

Portal object with `Application Data`, `Permit`, `record_id`, `Location ID`, `Owner`, and optionally `Structure`. Record identity matches `Application Data` / `record_id` (PERMIT_NUMBER usually equals `record_id` aside from type-code suffix drift). The nested `Permit` block matches that identity on only 155 / 630 non-empty Permit rows; the other 475 are location-joined neighbors and must not drive dates or status.

| INFERRED_SCHEMA | n |
| --- | ---: |
| app_only_structure | 923 |
| app_only | 447 |
| permit_mismatched_structure | 434 |
| permit_aligned_structure | 107 |
| permit_aligned | 48 |
| permit_mismatched | 41 |

Canonical source fields:

| Target field | Primary source | Fallback / notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `Application Data.Status` | Aligned `Permit.Permit Status` when present (e.g. REVOKED) |
| FILE_DATE | `Application Data.Date` for In Review only | No apply date for Active/Final |
| PERMIT_DATE | Aligned `Permit.Issue Date` | Active `APPROVED` → `Application Data.Date` |
| FINAL_DATE | Aligned `Permit.Status Updated` | `Application Data.Date`; else latest inspection Date |

## Field assessment

### STATUS_NORMALIZED

All 2,000 values were missing (`STATUS_ORIGINAL` also null). Status is recovered from `Application Data.Status`, ignoring mismatched Permit Status:

| Application Data.Status | → | n (approx.) |
| --- | --- | ---: |
| CLOSED | Final | 1,550 |
| CERTIFICATE OF OCC ISSUED | Final | 229 |
| APPROVED | Active | 117 |
| IN PLAN CHECK | In Review | 12 |
| ON HOLD | In Review | 2 |

Aligned Permit overrides when present: `PERMIT REVOKED` → Inactive (8 total Inactive, including aligned revoked rows that had App Status CLOSED); `PERMIT ISSUED` → Active even if App Status is CLOSED (1 row); `FINAL INSPECTION COMPLETE` → Final.

After repair: Final 1,786; Active 117; In Review 14; Inactive 8; missing 75.

The 75 unrepaired rows are empty shells (65: null App Status and empty Permit) plus 10 mismatched rows with null App Status (Permit Status cannot be trusted).

### FILE_DATE

Universally missing before repair. DATA has no dedicated apply/submittal field. On aligned rows, `Application Data.Date` equals `Status Updated` in 130 / 140 cases and is never earlier than Issue Date — it is a close/status stamp, not a file date. Repair therefore fills FILE_DATE only for In Review rows from `Application Data.Date` (14 / 14). Active/Final FILE_DATE remains missing.

### PERMIT_DATE

Universally missing before repair. Valid Issue Date strings exist on 579 rows, but 51 are sentinel `00/00/00`, and most non-empty Permit blocks are mismatched. Only aligned Issue Dates are used (135 fills). Additionally, all 117 Active rows receive PERMIT_DATE: 11 from aligned Issue Date and 106 from `Application Data.Date` on APPROVED rows without an aligned Issue Date.

Coverage after repair:

- **Active:** 117 / 117 (100%)
- **Final:** 124 / 1,786 (6.9%) — only aligned Issue Date; remaining Final rows have empty or mismatched Permit blocks
- **In Review / Inactive:** 0% (no issuance stamp)

### FINAL_DATE

Universally missing before repair. For Final rows, fill from aligned `Status Updated`, else `Application Data.Date`, else latest non-null inspection Date. Result: 1,786 / 1,786 (100%). Non-Final rows stay empty (no spurious finals to clear in this sample).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1,925 | 0 | 2,000 → 75 |
| FILE_DATE | 14 | 0 | 2,000 → 1,986 |
| PERMIT_DATE | 241 | 0 | 2,000 → 1,759 |
| FINAL_DATE | 1,786 | 0 | 2,000 → 214 |

Date-order violations after repair: FILE>PERMIT=0, PERMIT>FINAL=0, FILE>FINAL=0.

## Not repairable

- 75 rows with no usable status signal (empty Application Data.Status; mismatched or empty Permit).
- FILE_DATE for Active/Final: no apply/submittal timestamp in DATA.
- PERMIT_DATE for most Final rows: Issue Date unavailable or attached to a different permit at the same Location ID.
- Inspection List dates are almost always null (only 41 rows have any inspection Date), so they rarely help FINAL_DATE beyond App Date / Status Updated.
