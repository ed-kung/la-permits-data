# Casselberry (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Casselberry was first. Its DATA is a citizen-portal scrape (`Status:`, `Permit Details`, `Reviews`, `Inspections`). STATUS_NORMALIZED was missing on 8 rows (Comments Sent / blank Status) and was fully filled. FILE_DATE was often a late review Completion or Issue Date rather than the earliest Review Start (1,340 FIXED, 129 FILLED; 14 remain empty). PERMIT_DATE already matched `Permit Details['Issue Date:']` whenever present; 8 Active/Final gaps were filled from review Completions. FINAL_DATE was universally missing and was filled on 410/411 Final rows from approved final / other inspections or review Completions.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Casselberry, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_casselberry.py` (`data_repair`)

## DATA schema

All records share the portal core keys. `Reviews` / `Inspections` are usually lists; a few rows emit a bare dict. Content variants:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `issued_insp_rev` | 1,126 | Issue Date + Inspections + Reviews |
| `issued_rev` | 494 | Issue Date + Reviews |
| `rev` | 322 | Reviews only |
| `issued` | 22 | Issue Date only |
| `insp_rev` | 14 | Inspections + Reviews |
| `issued_insp` | 8 | Issue Date + Inspections |
| `minimal` | 14 | none of the above |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (else Issue Date / approved final inspection inference) |
| FILE_DATE | earliest Review Start (else Completion; else Issue Date if FILE missing) |
| PERMIT_DATE | `Permit Details['Issue Date:']` (else latest approved / latest review Completion) |
| FINAL_DATE | latest approved final-like inspection, else any approved inspection, else review Completion, else Issue Date for Closed |

## Field assessments

### STATUS_NORMALIZED

8 missing; no incorrect mapped values among non-null rows. **8 FILLED:**

| After | `Status:` / evidence | n |
| --- | --- | ---: |
| In Review | Comments Sent | 2 |
| Active | blank Status + Issue Date | 4 |
| Final | blank Status + Approved Roof (Final) | 2 |

Cause: upstream left `STATUS_NORMALIZED` null when `STATUS_ORIGINAL` was `comments sent` or null while DATA still had usable status/dates. After repair: Active 1,209; Final 411; In Review 289; Inactive 91; none missing.

### FILE_DATE

Ideal: populated for all records.

- Before: 143 missing. Many populated values equaled a late Review Completion (e.g. Building Sufficiency / Approve for Payment) or Issue Date rather than the earliest Review Start.
- **129 FILLED** from Reviews (or Issue Date when Reviews had no dates).
- **1,340 FIXED** to earliest Review Start (else earliest Completion); 575 of those previously equaled Issue Date.
- Remaining: **14** with no dated Reviews and no Issue Date (mostly Online Application Received / empty workflow shells).

Coverage after repair: overall 99.3%; Active 100%; Final 99.8%; In Review 95.8%; Inactive 98.9%.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present, always matched `Permit Details['Issue Date:']` (top-level `Issue Date` is always null).
- **8 FILLED** on Final rows with blank Issue Date but dated Reviews.
- Remaining: **1 Final** shell with empty Reviews / Issue Date; In Review / Inactive keep incidental Issue Dates when the portal still shows them (23 / 16 rows) without changing `Status:`.

Coverage after repair: Active 100%; Final 99.8%.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: missing on all 2,000 rows (no dedicated FinalDate field in DATA).
- **410 FILLED** on Final rows: 146 from approved final-named inspections, 240 from other approved inspections, 22 from review Completions, 2 from Issue Date on Closed.
- Remaining: **1 Closed** shell with empty Inspections, Reviews, and Issue Date.

Coverage after repair: Final 99.8%; Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 8 | 0 | 8 → 0 |
| FILE_DATE | 129 | 1,340 | 143 → 14 |
| PERMIT_DATE | 8 | 0 | 350 → 342 |
| FINAL_DATE | 410 | 0 | 2,000 → 1,590 |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_casselberry.py`
