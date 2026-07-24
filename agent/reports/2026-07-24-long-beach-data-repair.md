# Long Beach CA data repair

**Summary:** Long Beach is the first (JURISDICTION, STATE) pair in the LA sample without an existing repair script. Its 2,000 sample rows use two DATA schemas (`project` 1,104; `listing` 896). Upstream left `FILE_DATE` and `PERMIT_DATE` empty for every row, left `STATUS_NORMALIZED` null on all listing rows (plus one `FeesDue` project row), and incorrectly copied `Status Date` into `FINAL_DATE` for most non-Final project rows. The repair fills 892 statuses, fills all 110 Active `PERMIT_DATE` values from `Status Date`, fills 8 missing Final `FINAL_DATE` values, and clears 296 spurious non-Final `FINAL_DATE` values. `FILE_DATE` cannot be recovered from DATA. Script: `agent/scripts/data_repair_ca_long_beach.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Long Beach"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Long Beach, CA (after Lomita in STATE/JURISDICTION order) |

| INFERRED_SCHEMA | n | Description |
| --- | --- | --- |
| `project` | 1,104 | Has `Project Status`, `Status Date`, `Project Number`, `Address`, `Project Description` |
| `listing` | 896 | Only `Description`, `Final Date`, `Project Type`, `Situs` (mostly code-enforcement / fire / health) |

Canonical fields in DATA:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `Project Status` (project); `Final Date` token or parseable date (listing) |
| `FILE_DATE` | *(none)* |
| `PERMIT_DATE` | `Status Date` when `Project Status == Permit Issued` |
| `FINAL_DATE` | Parseable `Final Date` if present; else `Status Date` when Closed |

Quirk: the field named `Final Date` is usually a **status token** (`Closed`, `Issued`, `Open`, `Void`, …), not a calendar date. Only 114 / 2,000 rows store an actual `MM/DD/YYYY` value there.

## Field assessment

### STATUS_NORMALIZED — 892 missing fillable (892 FILLED / 0 FIXED)

Project-schema mapping was already correct wherever present:

| Project Status | STATUS_NORMALIZED | n |
| --- | --- | --- |
| Closed | Final | 775 |
| Permit Issued | Active | 110 |
| Review / Additional Information… / Pre-App | In Review | 69 |
| Void / Abandonned / Expired | Inactive | 149 |
| FeesDue | *(was null)* → In Review | 1 |

Listing rows had no `Project Status` / `STATUS_ORIGINAL`. Status is inferred from the `Final Date` token (or from a parseable date → Final):

| Final Date (listing) | → STATUS_NORMALIZED | n filled |
| --- | --- | --- |
| Closed | Final | 754 |
| parseable date | Final | 76 |
| Open | In Review | 52 |
| ClosedPend | In Review | 1 |
| Void / Deleted | Inactive | 8 |

Five Fire Department listing rows have a null `Final Date` and remain missing status (no signal in DATA).

After repair: Final 1,605 · Inactive 157 · In Review 123 · Active 110 · null 5.

### FILE_DATE — universally missing, not fillable (0 FILLED / 0 FIXED)

No application / submittal timestamp exists in either schema. `Status Date` is a last-status-change stamp, not a file date, so it is not used as a proxy. All 2,000 rows remain missing `FILE_DATE`.

### PERMIT_DATE — empty; fillable for Active only (110 FILLED / 0 FIXED)

- **Active (Permit Issued):** all 110 rows get `PERMIT_DATE` from `Status Date` (the only issuance proxy; when `Final Date` is a real date it matches `Status Date`).
- **Final:** no separate issuance field. On Closed rows, `Status Date` is the close/final stamp, so it must not be copied into `PERMIT_DATE`. All 1,605 Final rows remain without `PERMIT_DATE`.

### FINAL_DATE — spurious on non-Final; incomplete on Final (8 FILLED / 296 FIXED)

Root cause: upstream treated `Status Date` (and occasionally a parseable `Final Date`) as `FINAL_DATE` regardless of lifecycle. Before repair, 109/110 Active, 62/69 In Review, and 124/149 Inactive rows carried a `FINAL_DATE`.

Repairs:

| Action | n | Detail |
| --- | --- | --- |
| FIXED (cleared) | 296 | Spurious `FINAL_DATE` on non-Final rows |
| FILLED | 8 | Closed project rows with null `Final Date` but usable `Status Date` |
| Unchanged correct | 767 | Closed project rows whose existing `FINAL_DATE` already matched parseable `Final Date` or `Status Date` |
| Unchanged correct | 76 | Listing rows with a parseable `Final Date` (status newly filled to Final) |

After repair: non-Final rows have 0% `FINAL_DATE`; Final rows have 851 / 1,605 (53.0%). The 754 still-missing Final dates are listing rows whose `Final Date` token is `"Closed"` with no calendar date in DATA.

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 892 | 0 | 897 → 5 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 110 | 0 | 2,000 → 1,890 |
| FINAL_DATE | 8 | 296 | 861 → 1,149 |

Ideal coverage after repair:

| Check | Result |
| --- | --- |
| Active `PERMIT_DATE` | 110 / 110 (100%) |
| Final `PERMIT_DATE` | 0 / 1,605 (no issuance field in DATA) |
| Final `FINAL_DATE` | 851 / 1,605 (53.0%) |
| Non-Final `FINAL_DATE` | 0 |
| Any `FILE_DATE` | 0 / 2,000 |

## Artifacts

- Script: `agent/scripts/data_repair_ca_long_beach.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/long_beach_repaired_sample.parquet`
