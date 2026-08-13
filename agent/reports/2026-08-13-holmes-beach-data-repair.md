# Holmes Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Holmes Beach. Its DATA is a flat city-portal export (same family as Anna Maria) with `Status` / `Issue Date` / `Permit#` or `Permit #`. `STATUS_NORMALIZED` had 73 nulls (mostly shifted receipting rows plus unmapped `Renew`) and 5 stale labels vs `DATA.Status`. `FILE_DATE` and `FINAL_DATE` are missing on every row and cannot be recovered from DATA. `PERMIT_DATE` already matched parseable `Issue Date` values; repair filled 1 Issued row that had lagged as In Review. Remaining Active/Final `PERMIT_DATE` gaps are rows where `Issue Date` holds work-description or receipt memo text.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. Holmes Beach was the first pair without `agent/scripts/fl/data_repair_fl_holmes_beach.py`.

## DATA shape

All 2,000 rows are flat dicts. Variants (`INFERRED_SCHEMA`):

| Schema | n | Keys |
| --- | ---: | --- |
| `flat_hash_wd` | 1,290 | `Permit#` + `Issue Date` + `Work Description` |
| `flat_space_wd` | 409 | `Permit #` + `Issue Date` + `Work Description` |
| `flat_hash` | 195 | `Permit#` + `Issue Date` (no work desc) |
| `flat_minimal` | 65 | no `Issue Date` (mostly shifted receipting) |
| `flat_space` | 41 | `Permit #` + `Issue Date` (no work desc) |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status`, else known token in `Sub Type` / `Permit Type` when Status is polluted |
| FILE_DATE | *(none — not in DATA)* |
| PERMIT_DATE | `Issue Date` when MM/DD/YYYY |
| FINAL_DATE | *(none — not in DATA)* |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,529; Active 213; In Review 117; null 73; Inactive 68.

Root causes of errors:

1. **Shifted receipting shells** — ~64 `City of Holmes Beach Receipts` rows put the payee/memo into `Status`, `"Receipting"` into `Address `, and the real status (`Under Review` / `Complete`) into `Sub Type`. Upstream left `STATUS_NORMALIZED` null.
2. **Unmapped `Renew`** — 8 permit-parking renewals with real `Issue Date` left null.
3. **Stale `STATUS_ORIGINAL`** — 5 rows where original lagged DATA (`issued` while Status=`Closed`; `expired`/`under review` while Status=`Issued`).

After repair: Final 1,533; Active 220; In Review 180; Inactive 67; **0 null**. Flags: **73 FILLED, 5 FIXED**.

### FILE_DATE

Missing on all 2,000 rows. DATA has no application/submittal date field. No fills/fixes. Ideal coverage remains 0%.

### PERMIT_DATE

Before: 302 missing. When present, values already matched parseable `Issue Date` (1,698 matches, 0 mismatches).

Issues:

- 1 Issued row had parseable `Issue Date` but null `PERMIT_DATE` because status was still In Review from a stale original → **FILLED** after status correction.
- 12 Active (`Approved`) and 62 Final rows still lack `PERMIT_DATE` because `Issue Date` holds work-description / receipt / denial text (or the key is absent) → not recoverable.

After: Active 208/220 (94.5%); Final 1,471/1,533 (96.0%); In Review 0/180 (correct — Issue Date is never a real date on those shells); Inactive 20/67 (issued-then-void/expired stamps retained).

Flags: **1 FILLED, 0 FIXED**.

### FINAL_DATE

Missing on all 2,000 rows. `Closed` → Final is clear from `Status`, but DATA exposes no completion / finaled / CO timestamp. `Issue Date` is issuance, not finalization, so it is not used. No fills/fixes.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 73 | 5 | 73 → 0 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 1 | 0 | 302 → 301 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Ideal-coverage gaps remaining:

- FILE_DATE: **all 2,000** (no application date in DATA)
- Active/Final missing PERMIT_DATE: **74** (non-date `Issue Date` / missing key)
- Final missing FINAL_DATE: **all 1,533** (no finaled timestamp in DATA)
- STATUS_NORMALIZED: **none**

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_holmes_beach.py`
- Repaired sample: `$AGENT_DATA_PATH/holmes_beach_repaired_sample.parquet`
