# West Park (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (in parquet appearance order) was **West Park**. DATA is a flat city-portal export (`Status`, `Issue Date`, optional `Close Date`) with two keying variants (`Permit #`/`Address ` vs `Permit#`/`Address`). Upstream left 74 statuses null and never populated `FILE_DATE` or `FINAL_DATE`. Repair filled all null statuses (and promoted 13 issued-but-lagging rows to Active), filled 680 `FINAL_DATE` values from parseable `Close Date`, and cleared 47 spurious Inactive `PERMIT_DATE` stamps. `FILE_DATE` cannot be repaired — no application/submittal field exists in DATA. After repair: STATUS 100%; FILE_DATE 0%; Active/Final PERMIT_DATE 1,609/1,688 (95.3%); Final FINAL_DATE 680/1,254 (54.2%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. West Park was the first pair without `agent/scripts/fl/data_repair_fl_west_park.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `portal_permit_space_issued` | 858 |
| `portal_permit_issued_finaled` | 680 |
| `portal_permit_space_minimal` | 176 |
| `portal_permit_minimal` | 168 |
| `portal_permit_issued` | 118 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status`, with parseable `Close Date` / `Issue Date` overrides; Sub Type / keyword recovery for shifted rows |
| FILE_DATE | *(none — no application date in export)* |
| PERMIT_DATE | `Issue Date` when `mm/dd/yyyy` (Active/Final only) |
| FINAL_DATE | `Close Date` when `mm/dd/yyyy` (Final only) |

Source quirk: `Issue Date` and `Close Date` often contain work-description text from a shifted export (341 / 118 non-date values respectively). The repair parser accepts only strict `mm/dd/yyyy` strings.

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,254; Active 421; Inactive 182; null 74; In Review 69.

After: Final 1,254; Active 434; Inactive 182; In Review 130; **0 null**.

| Issue | n | Cause |
| --- | ---: | --- |
| null → In Review | 63 | `Payment Needed` / On Hold / Permit Ready / garbled Status never mapped |
| null → Active | 11 | `Payment Needed` rows that already carry a real `Issue Date` |
| In Review → Active | 2 | `Under Review` with real `Issue Date` (portal lag) |

Flags: **74 FILLED, 2 FIXED**.

Already-correct mappings left unchanged: Closed→Final, Issued/Approved→Active, Denied/Expired/Void/Cancelled→Inactive, Under Review / Online Application Received→In Review.

### FILE_DATE

Missing on 2,000/2,000 before and after. DATA has no application, filed, or submitted timestamp — only `Issue Date` and (sometimes) `Close Date`. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing before: 344. After: 391 (net +47 from clearing Inactive stamps).

- **FILLED 0:** Every Active/Final row with a parseable `Issue Date` already had a matching `PERMIT_DATE` (1,656/1,656 calendar-day matches). Promoted Payment Needed / Under Review rows likewise already carried the stamp.
- **FIXED 47:** Cleared issuance stamps on Expired (28) / Cancelled (9) / Void (9) / Denied (1). Ideal rule keeps `PERMIT_DATE` only on Active/Final.

Active/Final coverage after repair: **1,609 / 1,688 (95.3%)**. Remaining 79 gaps: 55 `Approved` with description text in `Issue Date`, and 24 `Closed` with the same misaligned field — no alternate issuance timestamp in DATA.

### FINAL_DATE

Missing before: 2,000. After: 1,320.

- **FILLED 680:** All Closed rows whose `Close Date` parses as `mm/dd/yyyy`.
- **FIXED 0.**

Final coverage after repair: **680 / 1,254 (54.2%)**. Remaining 574 Closed rows lack a parseable close stamp (562 have no `Close Date` key; 12 have description text in that field). Five Closed rows have `Close Date` one day to a few weeks before `Issue Date` (source chronology; left as-is).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 74 | 2 | 74 → 0 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 0 | 47 | 344 → 391 |
| FINAL_DATE | 680 | 0 | 2,000 → 1,320 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_west_park.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_west_park_repaired.parquet`
