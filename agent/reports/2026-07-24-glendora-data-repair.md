# Glendora CA data repair

**Summary:** Glendora’s 2,000 sample records share one DATA schema (`permit_info_search_data`). Upstream dates already match `permit_info` when present. The main gaps are stale status (STATUS_ORIGINAL lags PermitStatus on ~26 rows; 17 rows have `PermitFinaledDate` but are not labeled Final) and missing dates on otherwise complete records. Repair remaps 27 statuses and fills 1 null, adds 83 `PERMIT_DATE` values (mostly from `PermitApprovedDate`), and 15 `FINAL_DATE` values (13 from `PermitFinaledDate`, 2 from finaling inspections). `FILE_DATE` needs no changes (already 100% aligned with `PermitAppliedDate`). Script: `agent/scripts/data_repair_ca_glendora.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Glendora"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Glendora, CA (after Alhambra … Glendale) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `permit_info_search_data` | 2,000 |

All rows share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (override to Final if `PermitFinaledDate` present) |
| `FILE_DATE` | `permit_info.PermitAppliedDate` |
| `PERMIT_DATE` | `permit_info.PermitIssuedDate`; fallback `PermitApprovedDate` |
| `FINAL_DATE` | `permit_info.PermitFinaledDate`; fallback for Final rows: finaling inspection `Completed` |

`PermitExpirationDate` is a validity window, not a completion date. `search_data` only carries identifiers (`RECORDID`, `PERMIT NO.`, `SITE ADDRESS`) — no date fields in this city.

## Field assessment

### STATUS_NORMALIZED — 1 missing + 27 stale / mislabeled

Upstream status was mapped from `STATUS_ORIGINAL`, which disagrees with current `PermitStatus` on 26 rows (e.g. `issued` / `under review` while the portal already shows `FINALED`, `ISSUED`, or `COMPLETED`).

| Issue | n | Notes |
| --- | --- | --- |
| `NOT APPLICABLE` → null status | 1 | Applied-only; no issued/approved/finaled |
| `PermitStatus=FINALED` but status Active/In Review | 13 | `STATUS_ORIGINAL` still issued / under review; all have `PermitFinaledDate` |
| `PermitStatus=ISSUED` but status In Review | 6 | Stale under review / corrections / cond approval |
| `PermitStatus=ISSUED` + `PermitFinaledDate` but status Active | 3 | Finaled date present; already had `FINAL_DATE` |
| `PermitStatus=COMPLETED` but status In Review | 3 | Fire-flow / plan-review jobs |
| `PermitStatus=APPROVED` but status In Review | 1 | |
| `UNDER REVIEW` + `PermitFinaledDate` but status In Review | 1 | Already had `FINAL_DATE` |

Repairs:

| Before | After | Reason | n | Flag |
| --- | --- | --- | --- | --- |
| null | In Review | `NOT APPLICABLE` (applied-only) | 1 | FILLED |
| Active | Final | `FINALED` / `ISSUED` + `PermitFinaledDate` | 15 | FIXED |
| In Review | Final | `FINALED` / `COMPLETED` / finaled date | 5 | FIXED |
| In Review | Active | `ISSUED` / `APPROVED` | 7 | FIXED |

After repair: Final 966, Active 750, In Review 155, Inactive 129 (**0 missing**).

### FILE_DATE — correct for all records (0 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- 2,000 / 2,000 match `PermitAppliedDate` exactly (0 mismatches, 0 missing).
- No repair needed.

### PERMIT_DATE — correct when Issued present; 83 fillable

- Ideal: populated for Active and Final.
- When both present, `PERMIT_DATE` always equals `PermitIssuedDate` (0 mismatches).
- 305 rows missing upstream; Active/Final with Issued or Approved can be filled after status remaps.

| Action | n | Source |
| --- | --- | --- |
| FILLED from `PermitApprovedDate` | 76 | 71 Active APPROVED; 5 Final (COMPLETED/FINALED) |
| FILLED from `PermitIssuedDate` | 7 | 6 ISSUED remapped from In Review; 1 FINALED |
| FIXED | 0 | |

After repair coverage: Active 716/750 (95.5%), Final 954/966 (98.8%).

**Not repairable:** 34 Active APPROVED and 12 Final (7 COMPLETED, 4 FINALED, 1 UNDER REVIEW-with-finaled) lack both Issued and Approved. `FILE_DATE` is not used as a proxy.

### FINAL_DATE — correct when Finaled present; 15 fillable

- Ideal: populated for Final.
- When both present, `FINAL_DATE` always equals `PermitFinaledDate` (0 mismatches).
- 13 rows had `PermitFinaledDate` but missing `FINAL_DATE` because status was not Final (stale labels); 2 Final FINALED rows lack `PermitFinaledDate` but have finaling inspections (`Type` contains FINAL with Result APPROVED / PARTIAL APPROVAL).

| Action | n |
| --- | --- |
| FILLED from `PermitFinaledDate` | 13 |
| FILLED from finaling inspection `Completed` | 2 |
| FIXED | 0 |

After repair coverage: Final 954/966 (98.8%); Active / In Review / Inactive all 0% (final dates only retained on Final).

**Not repairable:** 12 Final rows (10 COMPLETED fire-flow/plan-review with empty inspections; 2 FINALED with no usable finaling inspection).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 1 | 27 | 1 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 83 | 0 | 305 → 222 |
| `FINAL_DATE` | 15 | 0 | 1,061 → 1,046 |

## Artifacts

| Path | Description |
| --- | --- |
| `agent/scripts/data_repair_ca_glendora.py` | `data_repair(df)` implementation |
| `AGENT_DATA_PATH/glendora_repaired_sample.parquet` | Repaired 2,000-row sample with flag + `INFERRED_SCHEMA` columns |
