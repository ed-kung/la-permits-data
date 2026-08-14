# Satellite Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (file order) was **Satellite Beach**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`); all 2,000 rows share the same top-level key set. `Reviews` is usually a single dict (not a list). Eight `Admin Close` rows had null `STATUS_NORMALIZED` (filled as Inactive); 19 `Under Review` rows with Issue Date were Fixed In Review → Active. Upstream `FILE_DATE` often stored Review Completion instead of earlier Completeness Check Start (120 Fixed) or a post-issue Completion on legacy reopens (4 cleared). `PERMIT_DATE` already matched Issue Date wherever present (0 changes). `FINAL_DATE` was missing on every row; filled from latest Pass inspection for Final rows (212/218). After repair: STATUS 0 null; FILE_DATE 28.1%; Active/Final PERMIT_DATE 1,168/1,309 (89.2%); Final FINAL_DATE 212/218 (97.2%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in file order. Satellite Beach was the first pair without `agent/scripts/fl/data_repair_fl_satellite_beach.py`.

## DATA shape

All 2,000 rows share the same CitizenServe portal shell (no form-extra key variants). Inferred schema prefixes are all `portal_core`, with content suffixes:

| Schema | n | Role |
| --- | ---: | --- |
| `portal_core_issued_finaled` | 786 | Issue Date + Pass inspection |
| `portal_core_status_only` | 582 | Status only (no dated Reviews / Issue / Pass) |
| `portal_core_issued` | 456 | Issue Date, no Pass inspection |
| `portal_core_applied` | 149 | Dated Reviews only |
| `portal_core_finaled` | 27 | Pass inspection, no Issue Date |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (`Inspection Completed`/`Closed`→Final, `Issued`/`Approved`→Active, `Under Review`/`Online Application Received`→In Review, `Void`/`Admin Close`→Inactive; In Review + Issue Date → Active) |
| FILE_DATE | Earliest Completeness Check / Permit Review Start ≤ Issue; else earliest Completion ≤ Issue |
| PERMIT_DATE | `Permit Details["Issue Date:"]` (else top-level `Issue Date`) |
| FINAL_DATE | Latest Pass/Approved inspection date, floored at Issue when present |

## Field assessments

### STATUS_NORMALIZED

Before: Active 1,072; Inactive 428; In Review 274; Final 218; **8 null**. After: Active 1,091; Inactive 436; In Review 255; Final 218; **0 null**.

| Status: | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Issued | 904 | Active | Correct |
| Void | 428 | Inactive | Correct |
| Inspection Completed | 215 | Final | Correct |
| Approved | 168 | Active | Correct |
| Under Review | 167 | In Review (148) / → Active (19 with Issue) | 19 Fixed |
| Online Application Received | 107 | In Review | Correct |
| Admin Close | 8 | null | Filled Inactive |
| Closed | 3 | Final | Correct |

### FILE_DATE

Before: 565 populated (28.2%), 1,435 missing. All non-null values came from Reviews (437 matched Start, 128 matched Completion). Repair Fixed 124 rows (prefer earlier Start over Completion; clear 4 post-issue Completions with no on/before-Issue Start). After: 563 populated (28.1%). Remaining gaps are shells with empty or undated Reviews (most Issued / Inspection Completed / Void rows).

### PERMIT_DATE

Before/after: 1,242 populated. Every non-null `PERMIT_DATE` already equaled Issue Date (no sentinel `01/01/2000`). Active/Final still missing PERMIT_DATE: 141, all `Approved` with blank Issue Date (pre-issuance approval — not fillable). In Review after repair: 0 with PERMIT_DATE.

### FINAL_DATE

Before: 0 populated. Filled 212 Final rows from Pass inspections. Still missing on 6 Final rows (5 Inspection Completed with empty / non-Pass inspections; 1 Closed with no inspections).

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_satellite_beach.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 8 | 19 | 8 → 0 |
| FILE_DATE | 0 | 124 | 1,435 → 1,437 |
| PERMIT_DATE | 0 | 0 | 758 → 758 |
| FINAL_DATE | 212 | 0 | 2,000 → 1,788 |

Post-repair coverage:

- STATUS_NORMALIZED null: 0
- FILE_DATE overall: 563/2,000 (28.1%)
- Active/Final PERMIT_DATE: 1,168/1,309 (89.2%)
- Final FINAL_DATE: 212/218 (97.2%)
- Date order violations (FILE>PERMIT, PERMIT>FINAL, FILE>FINAL): 0

## Artifact

- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_satellite_beach_repaired.parquet`
