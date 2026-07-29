# Humboldt County (CA) data repair — 2026-07-28

Humboldt County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` has correct `FILE_DATE` (vs `date`) on every row, but `STATUS_NORMALIZED` is missing on nearly half the sample (Historic Permits), `PERMIT_DATE` is often stamped from Ready-to-Issue or CTIP-Completed instead of `Permit Issuance|Issued`, and two Active rows carry a `Final Inspection Complete` final date while still labeled Active. Repair fills 32 statuses, fixes 52 more, corrects 113 permit dates and clears 17 spurious ones, and fills/fixes 32 final dates. Residual Active/Final date gaps are historic shells without Issued / final workflow marks.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample appearance order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Humboldt County, CA** → `agent/scripts/ca/data_repair_ca_humboldt_county.py` (n=2,000).

## DATA schema

Accela scrape with spaced task-event keys (`Marked as `, ` on `). Two top-level key sets (full vs partial) plus content tags for Issued / Final Inspection Complete events, recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_full_empty_tasks` | 1,061 | full keys; no dated workflow events |
| `accela_partial_empty_tasks` | 449 | sparse keys; no dated events |
| `accela_full_issued` | 209 | Issued mark, no final mark |
| `accela_full_issued_finaled` | 162 | Issued + Final Inspection Complete / Final CO |
| `accela_full_other_events` | 107 | other dated workflow events only |
| `accela_full_finaled_only` | 10 | final marks, no Issued |
| `accela_partial_other_events` | 2 | sparse + other dated events |

Canonical fields: `status` → status; `date` → file; `Permit Issuance|Issued` → permit; `Inspection|Final Inspection Complete` (fallback `Certificate of Occupancy|Final CO Issued`, then approved Final* inspection `Status Date`) → final.

## Field assessment

### STATUS_NORMALIZED

- Missing on 949 / 2,000 (all Historic Permits with null `DATA.status`).
- Upstream mapping from `STATUS_ORIGINAL` / `DATA.status` is mostly correct for labeled rows (`issued`→Active, `finaled`/`CofO Issued`/`Business License Complete`→Final, cancel/expire→Inactive, plan-check queues→In Review).
- Incorrect mappings repaired:
  - `ARCHIVED` (48) and `Stop Work` (1) were In Review → **Inactive**
  - 2 `Issued` rows with `Final Inspection Complete` were Active → **Final**
  - 1 row with `STATUS_ORIGINAL=ready to issue` but `DATA.status=Issued` → **Active**
- Fillable nulls: 28 Historic Permits with approved Final* inspections → Final; 4 with other approved inspections → Active. Remaining 917 null-status historics have no usable inspections.
- **Repair:** 32 FILLED, 52 FIXED. Missing after: 917.

### FILE_DATE

- Missing on 0 / 2,000. Present values match `DATA.date` (and `search_data.Date`) on all 2,000 rows.
- **Repair:** 0 FILLED, 0 FIXED. Coverage 100%.

### PERMIT_DATE

- Missing on 1,614 / 2,000 (80.7%). Among present values, many do **not** match `Permit Issuance|Issued`:
  - ~81 used `Ready to Issue` (often the day before Issued)
  - ~24 used `Changes to Issued Permit …|Completed` (amendment close, not original issuance)
  - Remainder mostly match Issued (exact or ±1 day)
- Active missing PERMIT (386): almost none have Issued task events (historic conversions with inspections only) → unfillable from `DATA`.
- Spurious PERMIT on In Review (Ready to Issue, 12) and a few Inactive (5) → cleared.
- **Repair:** 0 FILLED, 130 FIXED (113 date corrections + 17 clears). Missing after: 1,631.
- Post-repair Active PERMIT coverage: 205/595 (34.5%); Final: 164/221 (74.2%).

### FINAL_DATE

- Missing on 1,828 / 2,000. When present, values match `Inspection|Final Inspection Complete` (172/172 before repair).
- 2 Active rows incorrectly carried FINAL from FIC → status upgraded to Final (dates retained).
- Final missing FINAL (21 before status repair): no FIC fill path for Business License Complete shells; 30 FILLED after repair are mostly newly Final historics from approved Final* inspection `Status Date`, plus FIC/CO where present.
- 2 Final rows had an earlier FINAL than the latest FIC mark → FIXED to latest FIC.
- **Repair:** 30 FILLED, 2 FIXED. Missing after: 1,798.
- Post-repair Final FINAL coverage: 202/221 (91.4%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 32 | 52 | 949 | 917 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 130 | 1,614 | 1,631 |
| FINAL_DATE | 30 | 2 | 1,828 | 1,798 |

Status distribution after repair: null 917 · Active 595 · Final 221 · Inactive 137 · In Review 130.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 595 | 100% | 34.5% | 0% |
| Final | 221 | 100% | 74.2% | 91.4% |
| In Review | 130 | 100% | 0% | 0% |
| Inactive | 137 | 100% | 0% | 0% |

Overall FILE_DATE coverage: 2,000 / 2,000 (100%). Active+Final PERMIT_DATE: 369 / 816 (45.2%).

Chronology: 0 `PERMIT < FILE` and 0 `FINAL < PERMIT` after repair (corrections removed RTI/CTIP stamps that broke issuance chronology).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_humboldt_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_humboldt_county_repaired.parquet`
