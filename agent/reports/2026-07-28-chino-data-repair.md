# Chino (CA) data repair — 2026-07-28

Chino was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` supports correcting 69 wrong statuses (68 plans-`Approved` rows previously Active → In Review; 1 `Applied` row with Issued + Finaled workflow → Final), fixing 1 `FILE_DATE` where Accela re-open bumped the top-level date past the original Application Submittal, and filling 5 missing `FINAL_DATE` values from Closed Close / final-titled inspection Status Dates. Populated `PERMIT_DATE` / `FINAL_DATE` values already matched workflow events exactly; the remaining 8 Final rows without a dated Permit Issuance Issued* event stay missing.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Chino, CA** → `agent/scripts/ca/data_repair_ca_chino.py` (n=2,000).

## DATA schema

Nearly all rows share Accela portal JSON with core keys (`address`, `date`, `status`, `tasks`, `search_data`, `details`, …). Six sparse rows omit optional blocks (`inspections`, `fees_details`, `contacts`, `conditions`, `related_records`, `address_lines`). Canonical fields:

| Source | Field |
| --- | --- |
| `DATA.status` / `search_data.Status` (+ Issued / Finaled workflow upgrades) | `STATUS_NORMALIZED` |
| Earliest of `DATA.date`, `search_data.Date`, Application Submittal first-touch marks | `FILE_DATE` |
| Earliest Permit Issuance `Issued` / `Issued Revision` / `Issued Deferred` | `PERMIT_DATE` |
| Earliest Inspections `Finaled` (fallback: Closed `Close`, then final-titled inspection Status Date) | `FINAL_DATE` |

`INFERRED_SCHEMA` content variants:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_issued_finaled` | 1,375 | Issued* + final date evidence |
| `portal_issued` | 382 | Issued present, no final date |
| `portal_application_only` | 177 | Top-level / Application Submittal dates only |
| `portal_final_only` | 66 | Final date present, no Issued |

## Field assessment

### STATUS_NORMALIZED

- Present on all 2,000. Upstream mapped from `STATUS_ORIGINAL`, which mirrors `DATA.status` (case aside) on every row — no blank / lagged original labels.
- Mis-mapping: `Approved` (plans / admin approval, not permit issuance) was stored as Active (69). Only 1 of those has a dated Permit Issuance Issued event; the other 68 lack issuance and should be In Review.
- Status lag: 1 `Applied` / In Review row already has Permit Issuance Issued + Inspections Finaled (and populated PERMIT/FINAL columns) → should be Final.
- Inspections Finaled alone does **not** promote Issued → Final when `DATA.status` is still Issued (no such rows in sample).
- **Repair:** 0 FILLED, 69 FIXED (68 Active→In Review; 1 In Review→Final). Missing after: 0.

### FILE_DATE

- Present on all 2,000; every value matched `DATA.date` before repair.
- 1 Closed planning-style row had Accela re-open bump `DATA.date` (2024-02-29) after Application Submittal Accepted for Review (2024-01-31).
- **Repair:** 0 FILLED, 1 FIXED. Coverage 2,000 / 2,000 (100%). Chronology clean after repair.

### PERMIT_DATE

- Missing on 243 / 2,000 (12.2%). When present (1,757), every value matched the earliest Permit Issuance Issued* mark (0 incorrect).
- Active missing PERMIT before repair: 68 — all `Approved` without Issued events; remapped to In Review so PERMIT is no longer expected.
- Final missing PERMIT: 8 — Permit Issuance task absent or TBD-only; not fillable from DATA.
- The 1 In Review row that carried PERMIT was promoted to Final (status lag); no clear needed.
- **Repair:** 0 FILLED, 0 FIXED. Missing after: 243.
- Post-repair Active PERMIT coverage: 417/417 (100%); Final: 1,306/1,314 (99.4%); Active+Final: 1,723/1,731 (99.5%); In Review: 0/223 by design.

### FINAL_DATE

- Missing on 691 / 2,000 (34.6%). When present (1,309), every value matched Inspections `Finaled` exactly (0 incorrect).
- Final missing FINAL before repair: 5. All fillable: 3 from Closed `Close`, 2 from final-titled inspection Status Date (`Final Electrical` / `Building Department Final` Approved).
- Non-Final with FINAL before repair: 1 (`Applied` status-lag row) — retained after promotion to Final.
- **Repair:** 5 FILLED, 0 FIXED. Missing after: 686.
- Post-repair Final FINAL coverage: 1,314/1,314 (100%); Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 69 | 0 | 0 |
| FILE_DATE | 0 | 1 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 243 | 243 |
| FINAL_DATE | 5 | 0 | 691 | 686 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,313 | 1,314 |
| Active | 485 | 417 |
| In Review | 156 | 223 |
| Inactive | 46 | 46 |

Chronology after repair: `PERMIT < FILE` = 0; `FINAL < PERMIT` = 0.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_chino.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_chino_repaired.parquet`
