# Oakland (CA) data repair — 2026-07-24

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for Oakland (first CA-sample jurisdiction lacking a repair script). Wrote `agent/scripts/data_repair_ca_oakland.py`. On the 2,005-row sample: 79 status fills + 8 status fixes; 75 permit fills + 47 permit fixes; 403 final fills + 15 final fixes; FILE_DATE already complete and correct. Residual date gaps are mostly **pre-2014 Accela migration shells** (status/date present, empty dated workflows) plus Active planning approvals and Permit Issued rows whose Permit Issuance events are still TBD.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in `permits_ca_sample.parquet` first-appearance order. Los Angeles and San Diego already had repair scripts. **Oakland (CA)** was the first without `agent/scripts/data_repair_ca_oakland.py`.

## DATA schema

Accela Citizen Access scrape (same family as Santa Monica / Culver City). All 2,005 rows share the same top-level keys (`status`, `date`, `tasks`, `inspections`, `search_data`, …). `INFERRED_SCHEMA` distinguishes workflow richness:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `tasks_only` | 1,049 | tasks present, no inspections |
| `tasks_inspections` | 873 | both tasks and inspections |
| `header_only` | 83 | empty tasks and inspections |

Useful fields: `status` / `search_data.Status`, `date` / `search_data['File Date']`, workflow `tasks[].events` (keys often have trailing spaces: `Marked as `, ` on `), and `inspections[].Title` / `Status` / `Status Date`.

## Field assessment

### STATUS_NORMALIZED

Before: Final 926, Inactive 520, Active 328, In Review 143, missing 88.

Issues:
- **88 unmapped specialty statuses** (mostly housing/fire/code-enforcement: `Initial Inspection`, `Violation Verified`, `Abated - by Owner`, `CL-Insp-NoViolFound`, …) left `STATUS_NORMALIZED` null even though `DATA.status` was populated → FILLED via an expanded status map.
- **8 `No Violation Found`** rows labeled In Review; treated as closed compliant outcomes → FIXED to Final.
- **9 blank** `DATA.status` / search Status → not fillable.

After: Final 940, Inactive 530, Active 331, In Review 195, missing 9.

### FILE_DATE

0 missing; all 2,005 match `DATA.date` (and `search_data['File Date']`). No repairs.

### PERMIT_DATE

1,410 missing. Ideal: populated for Active and Final.

- Canonical source: `Permit Issuance` / `Issued` (also `Permit Issued`, `Issued/Inspection Required`).
- **47 rows** had PERMIT_DATE set to `Ready to Issue*` (fee-due / ready) instead of the later `Issued` event → FIXED.
- Fillable gaps: 70 `Approved` planning/zoning rows from `Application Intake` / `Zoning Review` / `Closure` approval events; 2 OTC issuance; 3 Final with recoverable Issued/OTC dates.
- Not fillable: ~182 Active (esp. `Permit Issued` with TBD Permit Issuance events; zoning/DOT types) and ~585 Final — **496 of those Final gaps are pre-2014**.

### FINAL_DATE

1,718 missing. Ideal: populated for Final.

- Canonical: `Inspection` / `Final*` (latest); fallback: inspections titled `Final*` with Pass/APPROVED; then C of O / Closure.
- **403 fills**, almost all from final inspection history on older Final rows (2000–2013) that lack dated task events.
- **10 Final rows** used an earlier final signal → FIXED to the latest Final* inspection/task date.
- **5 spurious** FINAL_DATE on Active/Inactive → cleared.
- Not fillable: 255 Final with no Final* task and no Final* inspection result (234 of those also have empty inspections).

## Why dates are missing

### Pre-2014 Accela migration shells (main cause)

Rows filed before ~2014 almost never have dated task events, but often retain inspection history:

| File-year band | n | Share with ≥1 dated task event | Share with inspections |
| --- | ---: | ---: | ---: |
| 2001–2013 | ~821 | ~1.6% | ~45% |
| 2014–2019 | ~560 | ~80% | ~35% |
| 2020–2025 | ~519 | ~84% | ~30% |

So `PERMIT_DATE` cannot be recovered for most pre-2014 Final/Active building permits, while `FINAL_DATE` often can be recovered from legacy final inspections.

### Smaller pockets

- **`Permit Issued` / Active with TBD Permit Issuance:** Accela status advanced without a dated Issued click.
- **Planning `Approved` without workflow dates:** some Zoning Clearance / DR Exemption rows have empty or TBD-only events.
- **Blank status (9):** no `DATA.status` to map.

## Repair performance (n=2,005)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 79 | 8 | 88 → 9 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 75 | 47 | 1,410 → 1,335 |
| FINAL_DATE | 403 | 15 | 1,718 → 1,320 |

Post-repair coverage by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 149 / 331 (45.0%) | 0 / 331 |
| Final | 355 / 940 (37.8%) | 685 / 940 (72.9%) |
| In Review | 6 / 195 (3.1%) | 0 / 195 |
| Inactive | 160 / 530 (30.2%) | 0 / 530 |

FILE_DATE: 2,005 / 2,005 (100%).

## Artifacts

- Script: `agent/scripts/data_repair_ca_oakland.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/processed_data/permits_ca_oakland_repaired.parquet`
