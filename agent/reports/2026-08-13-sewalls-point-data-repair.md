# Sewalls Point (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (file order) was **Sewalls Point**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`) with building-contractor and tree-permit form variants on top of the core shell. Upstream status mapping was already correct except one `On Hold` row with Issue Date (Fixed → Active). Upstream `FILE_DATE` almost always stored Issue Permit Completion / Issue Date rather than earlier Plan Review Start (1,889 Fixed; 33 missing filled). `PERMIT_DATE` already matched Issue Date wherever present (0 changes). `FINAL_DATE` was missing on every row; filled from latest Pass/Complete/Approved inspection for Final rows (1,359/1,428 = 95.2%). After repair: STATUS 0 null; FILE_DATE 99.85%; Active/Final PERMIT_DATE 1,611/1,629 (98.9%); Final FINAL_DATE 1,359/1,428 (95.2%); date-order violations 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Sewalls Point was the first pair without `agent/scripts/fl/data_repair_fl_sewalls_point.py` (after 208 earlier FL jurisdictions that already had scripts).

## DATA shape

2,000 rows. All share the CitizenServe portal shell; key-set variants add contractor lists (`portal_building`, n≈1,197) or tree-permit fields (`portal_tree`, n=90); remainder are `portal_core` (n≈713). Content suffixes mark recoverable dates:

| Schema | n |
| --- | ---: |
| `portal_building_issued_finaled` | 1,052 |
| `portal_core_issued_finaled` | 436 |
| `portal_core_issued` | 229 |
| `portal_building_issued` | 144 |
| `portal_tree_issued_finaled` | 49 |
| `portal_core_applied` | 47 |
| `portal_tree_applied` | 24 |
| `portal_tree_issued` | 15 |
| other (`*_finaled` / `*_applied`) | 4 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (`Closed`→Final, `Issued`/`Approved`→Active, `On Hold`→In Review, `Expired`/`Voided`/`Denied`/`Revoked`→Inactive; In Review + Issue Date → Active) |
| FILE_DATE | Earliest Plan Review / Revision Review Start ≤ Issue (excluding Issue Permit / Issue Revision); else earliest Completion ≤ Issue |
| PERMIT_DATE | `Permit Details["Issue Date:"]` (else top-level `Issue Date`) |
| FINAL_DATE | Latest Pass/Complete/Approved inspection date, floored at Issue when present |

## Field assessments

### STATUS_NORMALIZED

Before/after mostly stable. No nulls. One `On Hold` row already carried Issue Date and inspections → Fixed In Review → Active. Remaining two `On Hold` rows stay In Review (blank Issue Date).

| Status: | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 1,428 | Final | Correct |
| Expired | 336 | Inactive | Correct |
| Issued | 199 | Active | Correct |
| Voided | 29 | Inactive | Correct |
| On Hold | 3 | In Review (2) / → Active (1 with Issue) | 1 Fixed |
| Denied | 3 | Inactive | Correct |
| Revoked | 1 | Inactive | Correct |
| Approved | 1 | Active | Correct (blank Issue Date; Awaiting Payment — PERMIT stays missing) |

### FILE_DATE

Before: 1,966 populated (34 missing). Upstream value almost always equaled Issue Permit Completion / Issue Date (1,727 matched Issue Date; only 79 matched Plan Review Start). Repair Fixed 1,889 rows to earlier Plan Review Start (on/before Issue) and Filled 33 of 34 missing from Review Start. After: 1,997 populated (3 still missing — shells with no usable Review Start/Completion). Date-order FILE > PERMIT: 0 after repair.

### PERMIT_DATE

Before/after: 1,925 populated. Every non-null `PERMIT_DATE` already equaled `Permit Details["Issue Date:"]` (0 Fixed/Filled). Active/Final still missing PERMIT_DATE: 18 — all blank Issue Date (`Closed` 17, `Approved` 1). In Review after repair: 0 with PERMIT_DATE.

### FINAL_DATE

Before: 0 populated. Filled 1,359 Final rows from Pass/Complete/Approved inspections (1,275 had a final-type inspection; 84 used a non-final Pass). Still missing on 69 Final (`Closed`) rows: 62 empty Inspections, 7 inspections with no Pass/Complete/Approved status. Non-Final statuses correctly keep FINAL_DATE null.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_sewalls_point.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1 | 0 → 0 |
| FILE_DATE | 33 | 1,889 | 34 → 3 |
| PERMIT_DATE | 0 | 0 | 75 → 75 |
| FINAL_DATE | 1,359 | 0 | 2,000 → 641 |

Post-repair coverage:

- STATUS_NORMALIZED null: 0
- FILE_DATE overall: 1,997/2,000 (99.85%)
- Active/Final PERMIT_DATE: 1,611/1,629 (98.9%)
- Final FINAL_DATE: 1,359/1,428 (95.2%)
- Date order violations (FILE>PERMIT, PERMIT>FINAL, FILE>FINAL): 0

## Artifact

- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_sewalls_point_repaired.parquet`
