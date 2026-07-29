# Napa County (CA) data repair — 2026-07-28

Napa County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` supports filling 26 null statuses, fixing 20 wrong statuses (Issuance Extended / Revision Process → Active; Approved → In Review), filling 138 missing `PERMIT_DATE` values from older Issued-task Approved* marks, and filling 1,277 of 1,298 Final rows’ missing `FINAL_DATE` from Time Tracking Permit Final, Closure CLOSED, or post-issuance approved Final* inspections. `FILE_DATE` was already correct for all 1,999 rows. Remaining gaps are mostly historic shells with empty Issuance / Final workflow tasks.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Napa County, CA** → `agent/scripts/ca/data_repair_ca_napa_county.py` (n=1,999).

## DATA schema

Nearly all rows share the full Accela portal key set (`address`, `date`, `status`, `tasks`, `inspections`, `search_data`, `details`, …). One sparse row omits optional blocks (`contacts`, `inspections`, `fees_details`, …). Canonical fields:

| Source | Field |
| --- | --- |
| `DATA.status` / `search_data.Status` (+ Issuance Issued/Re-Issued upgrade) | `STATUS_NORMALIZED` |
| `DATA.date` / `search_data['File Date']` | `FILE_DATE` |
| Issuance `Issued`\|`Re-Issued` (fallback: Issued-task `Approved*`) | `PERMIT_DATE` |
| Time Tracking `Permit Final` → Closure `CLOSED` → approved Final* insp | `FINAL_DATE` |

`INFERRED_SCHEMA` content variants:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_full_issued_finaled` | 894 | Issuance/Issued + final date source |
| `accela_full_finaled_only` | 468 | Final date source, no issuance |
| `accela_full_other_events` | 413 | Other dated workflow / top-level date only |
| `accela_full_issued` | 223 | Issuance present, no final date source |
| `accela_partial_other_events` | 1 | Sparse key set |

## Field assessment

### STATUS_NORMALIZED

- Missing on 26 / 1,999: `Review to Applicant` (22) and `Pending Documents` (4) were unmapped upstream → FILLED as In Review.
- Incorrect mappings repaired:
  - `Issuance Extended` (8) and `Revision Process` with Issuance Issued (3) left In Review despite dated issuance → FIXED to Active.
  - `Approved` (9) left Active; these are mostly History Permit Plus shells with no Issuance events (plans/history approved, not issued) → FIXED to In Review.
- Inactive terminals (`Expired Permit`, `Closed Application`, `Void`, …) and `Finaled` / `Issued` / `Re-Issued` / `Renewed` already matched the intended labels.
- Final Inspection / Permit Final alone does **not** promote Issued → Final when `DATA.status` is still Issued. Code-enforcement `Issued` marks (`Active` / `Passed`) are not treated as building-permit issuance.
- **Repair:** 26 FILLED, 20 FIXED. Missing after: 0.

### FILE_DATE

- Present on all 1,999; every value matched `DATA.date` (and `search_data['File Date']` when present).
- Application Acceptance dates never precede the top-level file date in this sample (no Accela re-open bump).
- **Repair:** 0 FILLED, 0 FIXED. Coverage 1,999 / 1,999 (100%).

### PERMIT_DATE

- Missing on 1,054 / 1,999 (52.7%). When present and an Issuance Issued/Re-Issued event exists, values matched that event (0 incorrect).
- Modern Accela path: Issuance `Issued`/`Re-Issued` (available on ~949 rows). Older converted path: Issued-task `Approved*` (fills 138 Finaled rows that lack an Issuance block).
- Unfillable Active: 19 Issued rows with empty Issuance events (mostly 2024–2025 OTC HVAC/roof/water-heater replacements, plus a few early-2000s shells).
- Unfillable Final: 459 Finaled shells—concentrated in file years 2000–2006—with neither Issuance nor Issued-task Approved* dates.
- **Repair:** 138 FILLED, 0 FIXED. Missing after: 916.
- Post-repair Active PERMIT coverage: 86/105 (81.9%); Final: 839/1,298 (64.6%); Active+Final: 925/1,403 (65.9%).

### FINAL_DATE

- Missing on all 1,999 upstream (100%).
- Fill sources for Finaled: Time Tracking `Permit Final` (350), Closure `CLOSED`/`Closed` (when no TT), else approved Final* inspections with date on/after issuance (or file date). Preferred inspection titles: Permit Final / Final Building / Final Occupancy / A7–Final Building.
- Pre-issuance “final” fire/review inspections are ignored (one B10-01276 case would otherwise set FINAL before PERMIT).
- Unfillable: 21 Finaled shells with no Permit Final, Closure, or post-issuance approved Final* inspection (mostly empty-inspection historic records; a few with only `No Inspection` Permit Final stubs).
- **Repair:** 1,277 FILLED, 0 FIXED. Missing after: 722 (21 of which are Final; remainder are non-Final by design).
- Post-repair Final FINAL coverage: 1,277/1,298 (98.4%); Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 26 | 20 | 26 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 138 | 0 | 1,054 | 916 |
| FINAL_DATE | 1,277 | 0 | 1,999 | 722 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,298 | 1,298 |
| Inactive | 328 | 328 |
| In Review | 244 | 268 |
| Active | 103 | 105 |
| (null) | 26 | 0 |

Chronology after repair: `PERMIT < FILE` = 0; `FINAL < PERMIT` = 0.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_napa_county.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_napa_county_repaired.parquet`
