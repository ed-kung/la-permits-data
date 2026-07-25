# Chicago IL data repair

**Summary:** All 35 `(JURISDICTION, STATE)` pairs in `permits_la_sample.parquet` already have repair scripts (Whittier was last). The first uncovered pair in `permits_top50_sample.parquet` is Chicago, IL (1,998 rows). Chicago DATA is a flat City of Chicago open-data payload with two schemas (`status_milestone` 1,989; `legacy_flat` 9). Main defects: `STATUS_NORMALIZED` is 100% missing (only 113 rows have a usable `PERMIT_STATUS`); one re-issued row keeps stale 2010 `FILE_DATE`/`PERMIT_DATE` while DATA has 2024 dates; `FINAL_DATE` is entirely absent from DATA and cannot be recovered. Script: `agent/scripts/data_repair_il_chicago.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_top50_sample.parquet` |
| Filter | `JURISDICTION == "Chicago"`, `STATE == "IL"` |
| N | 1,998 |
| Note | `permits_la_sample.parquet` has no remaining uncovered jurisdictions |

| INFERRED_SCHEMA | n |
| --- | --- |
| `status_milestone` | 1,989 |
| `legacy_flat` | 9 |

Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `PERMIT_STATUS` (non-empty only) |
| `FILE_DATE` | `APPLICATION_START_DATE` |
| `PERMIT_DATE` | `ISSUE_DATE` |
| `FINAL_DATE` | *(none — not present in DATA)* |

Status map: `ACTIVE` → Active; `COMPLETE` → Final; `EXPIRED` / `CANCELLED` → Inactive; `OPEN` → In Review.

`PERMIT_MILESTONE` aligns with `PERMIT_STATUS` (e.g. COMPLETE↔COMPLETE, ACTIVE↔INSPECTIONS / INSPECTION ELIGIBLE / PERMIT ISSUED) but adds no independent status signal.

## Field assessment

### STATUS_NORMALIZED — 1,998 missing; 113 fillable

Upstream left status entirely null (`STATUS_ORIGINAL` also null).

| `PERMIT_STATUS` | n | → STATUS_NORMALIZED |
| --- | ---: | --- |
| `ACTIVE` | 97 | Active |
| `COMPLETE` | 11 | Final |
| `EXPIRED` | 2 | Inactive |
| `CANCELLED` | 1 | Inactive |
| `OPEN` | 2 | In Review |
| empty string | 1,876 | cannot determine |
| key absent (`legacy_flat`) | 9 | cannot determine |

The 1,885 undetermined rows all have an `ISSUE_DATE` (permits were issued), but DATA has no way to distinguish Active vs Final vs Inactive. Left missing rather than assuming Active.

After repair: Active 97, Final 11, Inactive 3, In Review 2, missing 1,885.

### FILE_DATE — nearly complete; 1 stale value fixed; 1 unfillable gap

- Ideal: application / submittal date for all records.
- 1,996 / 1,997 rows with both `FILE_DATE` and `APPLICATION_START_DATE` match at calendar day.
- FIXED 1: permit `B200024186` (`OPEN`) — row had 2010-04-16; DATA `APPLICATION_START_DATE` is 2024-07-25 (re-file / re-issue; DATA treated as authoritative).
- Missing 1: legacy electric permit `100125596` — row `FILE_DATE` null and `APPLICATION_START_DATE` empty; only `ISSUE_DATE` present (2006-07-19). Not used as a FILE_DATE substitute. Remains missing.

### PERMIT_DATE — complete; 1 stale value fixed

- Ideal: populated for Active and Final (also present for all other statuses here).
- 1,997 / 1,998 rows match `ISSUE_DATE` at calendar day before repair.
- FIXED 1: same `B200024186` row — 2010-06-30 → 2024-08-13 from `ISSUE_DATE`.
- After repair: 1,998 / 1,998 present. Active 97/97, Final 11/11.

### FINAL_DATE — entirely missing; not recoverable

- Ideal: populated for Final.
- No DATA key contains final / complete / close / expire / end / finish / sign-off date information.
- 11 `COMPLETE` rows confirm finalization via status/milestone but carry no completion date.
- FILLED 0, FIXED 0. Final coverage remains 0 / 11.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 113 | 0 | 1,998 → 1,885 |
| `FILE_DATE` | 0 | 1 | 1 → 1 |
| `PERMIT_DATE` | 0 | 1 | 0 → 0 |
| `FINAL_DATE` | 0 | 0 | 1,998 → 1,998 |

Coverage vs ideals (after repair):

| Ideal | Result |
| --- | --- |
| `FILE_DATE` for all | 1,997 / 1,998 (99.9%) |
| `PERMIT_DATE` for Active + Final | 108 / 108 (100%) |
| `FINAL_DATE` for Final | 0 / 11 (0%) |
| `STATUS_NORMALIZED` populated | 113 / 1,998 (5.7%) |

## Artifacts

- `agent/scripts/data_repair_il_chicago.py` — `data_repair(df)` with `INFERRED_SCHEMA` and `{FIELD}_FLAG` columns (`FILLED` / `FIXED`)
