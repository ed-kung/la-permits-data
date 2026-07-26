# Modesto (CA) data repair

**Summary:** Among CA sample jurisdictions lacking a repair script, Modesto was first. Its DATA JSON uses a uniform civic-portal schema (`permit_info` + `search_data`). Existing dates already matched `PermitAppliedDate` / `PermitIssuedDate` / `PermitFinaledDate` when present. The main defect was six `FINALED**` rows still labeled Active (stale `STATUS_ORIGINAL=issued`); remapping them to Final and filling `FINAL_DATE`, plus filling three missing `PERMIT_DATE` values from `PermitApprovedDate`, brings Active/Final permit and final-date coverage to 100% / 98.9% and 99.7% respectively.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked distinct `(JURISDICTION, STATE)` pairs in appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Modesto, CA** (2,001 sample rows).

## DATA schema

All 2,001 rows share top-level keys: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`.

Canonical fields under `permit_info` (mirrored in `search_data` for status / issued / finaled):

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `PermitStatus` |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, fallback `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` (fallback `search_data.FINALED`) |

Inferred schemas written by the repair:

- `permit_info` — 1,998 rows (Applied present)
- `permit_info_no_applied` — 3 rows (Issued present, Applied blank)

## Field assessment

### STATUS_NORMALIZED

No missing values. Mapping from `STATUS_ORIGINAL` was generally consistent with `PermitStatus`, except:

- **6 incorrect Active rows** where `PermitStatus=FINALED**` and `PermitFinaledDate` was populated, but `STATUS_ORIGINAL` lagged at `issued`. Cause: upstream normalization followed stale portal status text instead of current `PermitStatus` / finaled date in DATA.

Other statuses (`Finaled`, `Issued`/`ISSUED`, `Received`, `Expired`/`EXPIRED`, `Closed`, `APPROVED`, etc.) already matched the intended Active / Final / In Review / Inactive buckets.

### FILE_DATE

- Present and equal to `PermitAppliedDate` for all 1,998 rows where Applied exists (0 mismatches).
- **3 missing** (all Inactive `EXPIRED`): Applied blank in DATA; Issued is present but is not an application date, so not used as a proxy. Unfillable.

### PERMIT_DATE

- When both present, always matches `PermitIssuedDate` (1,862/1,862).
- Missing whenever Issued is blank (139 rows).
- **Active/Final gaps:** 18 rows lacked Issued. Of those, 3 had `PermitApprovedDate` and were fillable (2 Active `APPROVED`, 1 Final `FINALED**`). Remaining ~15 are mostly legacy Finaled records with neither Issued nor Approved — unfillable from DATA.

### FINAL_DATE

- When both present, always matches `PermitFinaledDate` (1,400/1,400). No spurious FINAL_DATE on non-Final rows.
- **6 missing with Finaled present** — exactly the Active/`FINALED**` status-lag cases above; fillable after status remap.
- **4 Final `FINALED**` rows** have blank Finaled / SD FINALED (inspections lack usable Completed dates) — unfillable.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_modesto.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 6 | 0 → 0 |
| FILE_DATE | 0 | 0 | 3 → 3 |
| PERMIT_DATE | 3 | 0 | 139 → 136 |
| FINAL_DATE | 6 | 0 | 601 → 595 |

After repair:

- STATUS: Final 1,410 / Active 436 / In Review 107 / Inactive 48
- FILE_DATE: 99.9% (1,998 / 2,001)
- PERMIT_DATE: Active 100%; Final 98.9%
- FINAL_DATE: Final 99.7% (1,406 / 1,410); 0% on non-Final

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_modesto.py`
- Repaired sample parquet: `AGENT_DATA_PATH/modesto_repaired_sample.parquet`
