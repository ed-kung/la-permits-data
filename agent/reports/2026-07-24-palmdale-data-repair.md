# Palmdale (CA) data repair

**Summary:** Palmdale’s 2,000 sample records are Accela Citizen Access payloads (`tasks` + `date` + `status`, or `search_data`-only listings). Upstream left 205 statuses unmapped (COC*, REGISTRD, VERIFIED, etc.) and mis-labeled COMPLIED / Registered as In Review. `FILE_DATE` was already complete and correct. `PERMIT_DATE` was present for only 109 rows (all matching `Issuance` / `Issued`); nearly all other Active/Final rows are pre-2023 migrations with empty task events and cannot be filled. `FINAL_DATE` is entirely missing — Inspections events are TBD placeholders with no Final/Closed dates. Repair script: `agent/scripts/data_repair_ca_palmdale.py`.

## Data & schemas

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `tasks` | 1,983 | Full ACA record: `status`, `date`, `tasks`, `search_data`, fees, etc. |
| `search_data_only` | 17 | Listing scrape only; empty Status; no workflow dates |

Canonical sources:

| Field | Source in DATA |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (case-normalized Accela codes) |
| `FILE_DATE` | `DATA.date` / `search_data.Date` |
| `PERMIT_DATE` | `Issuance` / `Issued`; fallback `Issuance` / `Registered` |
| `FINAL_DATE` | `Inspections` / Final* or `Closed` / Close (none present in sample) |

## Field assessment

### STATUS_NORMALIZED

| | Before | After |
| --- | ---: | ---: |
| Missing | 205 | 17 |
| Final | 1,151 | 1,278 |
| Active | 209 | 294 |
| In Review | 121 | 97 |
| Inactive | 314 | 314 |

- **FILLED 188:** unmapped codes — COC5 (77), REGISTRD (49), COC3 (16), 1st NOT. (15), VERIFIED (13), INSPCTED (8), COC-3 (4), FORMAL (2), COC1 (2), SCHLED (1), COC-5 (1).
- **FIXED 42:** COMPLIED In Review→Final (27); Registered In Review→Active (13); stale `In Review` despite `Issuance`/`Issued` → Active (2).
- **Unfillable 17:** `search_data_only` rows with no status.

### FILE_DATE

Already populated for all 2,000 rows and matches `DATA.date` (or `search_data.Date`) exactly. **FILLED 0 / FIXED 0.**

### PERMIT_DATE

| | Before | After |
| --- | ---: | ---: |
| Missing | 1,891 | 1,884 |

- Existing 109 values all match `Issuance` / `Issued` (0 incorrect).
- **FILLED 7:** `Issuance` / `Registered` on Active rental-registration rows after status repair.
- **Unfillable:** 1,473 remaining Active/Final gaps have *no* real task event dates (empty events on ~1,756 tasks rows, almost all pre-2023). Coverage after repair: Active 41/294 (13.9%), Final 58/1,278 (4.5%).

### FINAL_DATE

Missing on all 2,000 rows before and after. Inspections tasks exist but events are `Marked as TBD` / `on TBD`. No Final, Finaled, or Closed dates appear in the sample. **FILLED 0 / FIXED 0.**

## Repair performance

```
STATUS_NORMALIZED:  FILLED 188   FIXED 42   missing 205 → 17
FILE_DATE:          FILLED   0   FIXED  0   missing   0 → 0
PERMIT_DATE:        FILLED   7   FIXED  0   missing 1891 → 1884
FINAL_DATE:         FILLED   0   FIXED  0   missing 2000 → 2000
```

## Artifacts

- Script: `agent/scripts/data_repair_ca_palmdale.py` (`data_repair`)
- Input: `MY_DATA_PATH/processed_data/permits_la_sample.parquet` (Palmdale / CA)
