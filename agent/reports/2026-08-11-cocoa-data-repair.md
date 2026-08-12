# Cocoa (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Cocoa was first. Its DATA is a citizen-portal scrape (`Status:`, `Permit Details`, `Reviews`, `Inspections`). STATUS_NORMALIZED was already mapped for every row; one Closed/Final label disagreed with DATA `Status:=Approved` and was FIXED to Active. FILE_DATE was usually a late Issue Permit Completion or Issue Date rather than the earliest Review Start (1,936 FIXED, 17 FILLED; 1 empty shell remains). PERMIT_DATE already matched `Permit Details['Issue Date:']` whenever present; 139 Active/Final gaps were filled from review Completions. FINAL_DATE was universally missing and was filled on all 1,411 Final rows (mostly approved final-named inspections).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Cocoa, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_cocoa.py` (`data_repair`)

## DATA schema

All records share the portal core keys. Top-level `Issue Date` is always null; the usable issuance date lives in `Permit Details['Issue Date:']`. Form fields vary (residential vs commercial value, balance due, subcontractors, etc.). Content variants:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `issued_insp_rev` | 1,546 | Issue Date + Inspections + Reviews |
| `issued_rev` | 281 | Issue Date + Reviews |
| `rev` | 160 | Reviews only |
| `insp_rev` | 11 | Inspections + Reviews |
| `issued_insp` | 1 | Issue Date + Inspections |
| `minimal` | 1 | none of the above |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (else Issue Date / approved final inspection inference) |
| FILE_DATE | earliest Review Start (else Completion; else Issue Date if FILE missing) |
| PERMIT_DATE | `Permit Details['Issue Date:']` (else latest approved / latest review Completion) |
| FINAL_DATE | latest approved final-like inspection, else any approved inspection, else review Completion, else Issue Date for Closed |

## Field assessments

### STATUS_NORMALIZED

No missing values. Upstream mapping from `STATUS_ORIGINAL` was consistent with DATA for 1,999/2,000 rows:

| `Status:` / STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Closed / closed | Final | 1,411 |
| Issued / issued | Active | 502 |
| Approved / approved | Active | 50–51 |
| Under Review / under review | In Review | 14 |
| Expired / expired | Inactive | 15 |
| Denied / denied | Inactive | 7 |

**1 FIXED:** DATA `Status:=Approved` while `STATUS_ORIGINAL=closed` / `STATUS_NORMALIZED=Final` (stale closed label; no Issue Date, empty Inspections) → Active. After repair: Active 553; Final 1,411; In Review 14; Inactive 22.

Note: ~78 Issued/Active rows have an approved final-named inspection while `Status:` remains Issued; status text is kept (not promoted to Final).

### FILE_DATE

Ideal: populated for all records.

- Before: 18 missing. Most populated values equaled Issue Permit Completion and/or Issue Date (~1,008 FILE==Issue), not the application/submittal date.
- **17 FILLED** from Reviews (or Issue Date when Reviews had no dates).
- **1,936 FIXED** to earliest Review Start (else earliest Completion); 989 of those previously equaled Issue Date.
- Remaining: **1** Under Review shell with empty Reviews / Inspections / Issue Date (`minimal` schema).

Coverage after repair: overall 99.95%; Active / Final / Inactive 100%; In Review 92.9%.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present, always matched `Permit Details['Issue Date:']` (1,828 rows; top-level `Issue Date` always null). **0 disagreements** with that source.
- **139 FILLED** on Active (50, all `Status:=Approved` with blank Issue Date) and Final (89 Closed shells) from latest review Completion.
- **1 FIXED** on the stale Closed→Approved row (PERMIT shifted to latest review Completion).
- Remaining missing: 14 In Review + 18 Inactive without Issue Date (ideal does not require PERMIT_DATE for those statuses).

Coverage after repair: Active 100%; Final 100%.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: missing on all 2,000 rows (no dedicated FinalDate field in DATA).
- **1,411 FILLED** on Final rows: 1,293 from approved final-named inspections, 17 from other approved inspections, 101 from review Completions.
- Remaining overall missing (589) are non-Final rows, which correctly stay empty.

Coverage after repair: Final 100%; Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1 | 0 → 0 |
| FILE_DATE | 17 | 1,936 | 18 → 1 |
| PERMIT_DATE | 139 | 1 | 171 → 32 |
| FINAL_DATE | 1,411 | 0 | 2,000 → 589 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_cocoa.py`
