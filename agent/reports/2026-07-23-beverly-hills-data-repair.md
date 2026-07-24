# Beverly Hills CA data repair

**Summary:** Beverly Hills’s 1,999 sample records use a single `permit_activity` DATA schema (`Permit` + `activity` plus parcel/people metadata). The dominant data-quality issue is `FINAL_DATE`: ~1,421 rows were populated with `activity['PERMIT EXPIRATION DATE']` instead of `activity['FINAL DATE']` (same Expire-vs-Final bug seen in Azusa). Status gaps are smaller but real: 25 unmapped raw statuses left `STATUS_NORMALIZED` null, and 7 `Final` rows were labeled `Active`. `FILE_DATE` / `PERMIT_DATE` already match `APPLIED DATE` / `ISSUED DATE` when those sources exist; only a handful of fillable gaps remain. Repair script: `agent/scripts/data_repair_ca_beverly_hills.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Beverly Hills"`, `STATE == "CA"` |
| N | 1,999 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Beverly Hills, CA (after Alhambra → Arcadia → Azusa) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `permit_activity` | 1,999 |

All rows share top-level keys `Permit`, `activity`, `apn`, `archive`, `custom`, `divisions`, `lso`, `people`. `Permit.STATUS` equals `activity.STATUS` on every row. Canonical dates live under `activity` (`APPLIED DATE`, `ISSUED DATE`, `FINAL DATE`, `PERMIT EXPIRATION DATE`); `Permit.ISSUED` mirrors `ISSUED DATE` whenever either is present.

## Field assessment

### STATUS_NORMALIZED — 25 missing + 7 incorrect (25 FILLED / 7 FIXED)

Existing mappings that needed no change:

| activity.STATUS | STATUS_NORMALIZED | n |
| --- | --- | --- |
| Final | Final | 1,140 (plus 7 mislabeled Active) |
| Issued | Active | 725 |
| Approved | Active | 83 |
| Withdrawn | Inactive | 19 |

Repairs:

| activity.STATUS | Before | Repair → | n | Flag |
| --- | --- | --- | --- | --- |
| Final | Active | Final | 7 | FIXED |
| Permit Ready to Issue (RTI) | (missing) | In Review | 10 | FILLED |
| Plan Review Withdrawn | (missing) | Inactive | 6 | FILLED |
| Approved For Garage Sale | (missing) | Active | 3 | FILLED |
| Permanent (Certificate of Occupancy) | (missing) | Final | 3 | FILLED |
| Permit Approved | (missing) | In Review | 1 | FILLED |
| Issued | (missing) | Active | 1 | FILLED |
| Investigation Pending | (missing) | In Review | 1 | FILLED |

The 7 FIXED rows all have a populated `FINAL DATE` in DATA and raw `STATUS=Final`; upstream left them as Active with null `FINAL_DATE`. After repair: Final 1,150, Active 812, Inactive 25, In Review 12 (0 missing).

### FILE_DATE — mostly correct (3 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- 1,986 / 1,999 rows already equal `activity['APPLIED DATE']`.
- 13 missing: none have `APPLIED DATE`; 3 have `START DATE` and were FILLED from it; 10 remain unfillable (no applied/start dates in DATA).
- No incorrect non-null values found.

After repair: 99.5%+ coverage on Active/Final/Inactive; 10 gaps remain.

### PERMIT_DATE — correct where `ISSUED DATE` exists (1 FILLED / 0 FIXED)

- Ideal: populated for Active and Final.
- When present, `PERMIT_DATE` always matches `activity['ISSUED DATE']` / `Permit.ISSUED` (1,857 / 1,857 before repair).
- Only 1 fillable gap: an `Issued` row with missing `STATUS_NORMALIZED` that also had `ISSUED DATE`.
- Remaining Active/Final gaps after repair (114) have empty `ISSUED DATE` in DATA:
  - Approved 56 (pre-issuance / never issued)
  - Final 34 (legacy rows)
  - Issued 22 (status says Issued but agency left issuance date blank)
  - Permanent 2 (CO without issuance date)

Expiration / start dates are not used as issuance proxies.

### FINAL_DATE — systematic Expire contamination (40 FILLED / 1,566 FIXED)

- Ideal: populated for Final; should reflect finaling / completion, not permit validity.
- Match analysis before repair: **1,421** `FINAL_DATE` values equal `PERMIT EXPIRATION DATE`; only **363** equal `FINAL DATE`; **211** missing; **4** unmatched.
- Among `STATUS_NORMALIZED=Final` before repair: 884 held the expiration date (840 of those also had a true `FINAL DATE` available), 222 already correct, 34 missing (33 fillable).

Repairs (Azusa-style):

| Issue | Count | Resolution |
| --- | --- | --- |
| Final rows with Expire-derived `FINAL_DATE` but true `FINAL DATE` present | ~840 | FIXED → `FINAL DATE` |
| Final rows missing `FINAL_DATE` with `FINAL DATE` in DATA | 40 | FILLED |
| Final rows with Expire-derived value and no true `FINAL DATE` | ~44 | FIXED → cleared (`NaT`) |
| Non-Final rows with spurious `FINAL_DATE` (mostly Expire) | ~682 | FIXED → cleared (`NaT`) |

After repair: **1,104 / 1,150 Final (96.0%)** have `FINAL_DATE`, all matching `activity['FINAL DATE']`. Active / In Review / Inactive have 0 `FINAL_DATE` values. The remaining 46 Final gaps have empty `FINAL DATE` in DATA (mixed Building/Electrical/Plumbing/Fire/ROW types); expiration is not used as a proxy.

## Repair function

`agent/scripts/data_repair_ca_beverly_hills.py` → `data_repair(df)`

- Overwrites incorrect / missing fields from DATA
- Adds `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`} and `INFERRED_SCHEMA`
- Rejects implausible date years (outside 1980–2035) before using them as fill/fix sources
- CLI preview on the LA sample:

```
STATUS_NORMALIZED: FILLED 25, FIXED 7; missing 25 → 0
FILE_DATE:         FILLED  3, FIXED 0; missing 13 → 10
PERMIT_DATE:       FILLED  1, FIXED 0; missing 142 → 141
FINAL_DATE:        FILLED 40, FIXED 1,566; missing 211 → 895
```

(The rise in `FINAL_DATE` missing count is expected: clearing ~1,500+ Expire-derived / non-Final values removes incorrect dates; true finals are restored where DATA provides them.)

## Artifacts

| Path | Role |
| --- | --- |
| `agent/scripts/data_repair_ca_beverly_hills.py` | Repair function + CLI stats |
| `agent/reports/2026-07-23-beverly-hills-data-repair.md` | This report |
