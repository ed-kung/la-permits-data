# Melbourne (FL) data repair

**Summary:** Melbourne was the first `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing repair script. Its `DATA` JSON is Tyler EnerGov (`entity` / `details` / `processing_status`). Upstream `STATUS_ORIGINAL` often lags live `CaseStatus` (especially `issued` kept after `Complete`). The repair fills 3 null statuses, fixes 61 stale statuses, fills 11 missing `PERMIT_DATE` and 41 missing `FINAL_DATE` values (plus clears 1 spurious final on Expired), and leaves `FILE_DATE` unchanged (already complete). After repair: 0 null `STATUS_NORMALIZED`; 100% `FILE_DATE`; 100% `PERMIT_DATE` for Active/Final; 100% `FINAL_DATE` for Final.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Melbourne, FL (n=2,000)
- Script: `agent/scripts/fl/data_repair_fl_melbourne.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_melbourne_repaired.parquet`

## DATA schema

Three key-set variants, labeled in `INFERRED_SCHEMA` with date-content suffixes:

| Schema prefix | n | Notes |
| --- | ---: | --- |
| `energov` | 1,811 | `entity`, `details`, `contacts`, `fees`, `processing_status` |
| `energov_full` | 188 | above + `reviews` / `holds` / `attachments` / `more_info` |
| `energov_minimal` | 1 | no `fees` |

Canonical mappings:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| `PERMIT_DATE` | `entity.IssueDate` (fallback `details.IssueDate`) |
| `FINAL_DATE` | `entity.FinalDate` → `details.FinalizeDate` → latest passed final-ish inspection in `processing_status` |

Status map (agency → normalized): `Complete`→Final; `Issued`→Active; `In Review` / `Fees Due` / `Awaiting Review` / `Ready to Invoice` / `Submitted*` / `On Hold`→In Review; `Void` / `Expired` / `Denied`→Inactive. One edge case upgrades `CaseStatus=Issued` + `PermitStatus=Complete` + final date → Final (entity lagged details).

## Findings by field

### STATUS_NORMALIZED

| Before | n |
| --- | ---: |
| Final | 1,197 |
| Inactive | 411 |
| Active | 254 |
| In Review | 135 |
| null | 3 |

Issues:

1. **Missing (3):** `STATUS_ORIGINAL=awaiting review` was unmapped → null. Fillable from `CaseStatus=Awaiting Review` → In Review.
2. **Stale (61):** `STATUS_ORIGINAL` lagged `entity.CaseStatus`. Largest transitions: Active→Final (37; `issued` while Case=`Complete`), In Review→Active (8), In Review→Inactive (7; mostly `fees due` while Case=`Expired`), In Review→Final (3).

After repair: Final 1,237 / Inactive 417 / Active 223 / In Review 123 / null 0. Flags: **FILLED 3, FIXED 61**.

### FILE_DATE

Already populated for all 2,000 rows; calendar day matches `entity.ApplyDate` in every case. No fills or fixes. (`details.ApplyDate` can be +1 UTC calendar day vs entity; entity is preferred and matches the upstream column.)

### PERMIT_DATE

| Before | Missing |
| --- | ---: |
| Overall | 343 (17.2%) |
| Active | 0 |
| Final | 0 |
| In Review | ~98.5% (expected) |
| Inactive | ~50% (many Void never issued) |

Issues repaired:

- **FILLED 11:** IssueDate present but `PERMIT_DATE` null on rows whose corrected status is Active/Final (stale status had kept them out of Active/Final).
- **FIXED 1:** cleared a spurious `PERMIT_DATE` on an In Review row.

After repair: Active/Final **100%** with `PERMIT_DATE`; In Review **0%** (cleared). Remaining 333 missing are almost entirely Inactive (Void/Expired never issued) — not fillable from `DATA`.

### FINAL_DATE

| Before | Notes |
| --- | --- |
| Missing 803 | Expected for non-Final; also 40 Complete shells mislabeled Active/In Review lacked `FINAL_DATE` |
| Final completeness | 1,196 / 1,197 (one Complete had null FinalDate/FinalizeDate but had passed final inspections) |
| Spurious | 1 Expired Inactive row carried FinalDate |

Repaired: **FILLED 41** (status fixes to Final + inspection fallback), **FIXED 1** (clear Expired). After repair: Final **1,237 / 1,237 (100%)**; non-Final **0%**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 61 | 3 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 11 | 1 | 343 → 333 |
| FINAL_DATE | 41 | 1 | 803 → 763 |

Post-repair ideal-field checks:

- Any missing `FILE_DATE`: **0**
- Active/Final missing `PERMIT_DATE`: **0**
- Final missing `FINAL_DATE`: **0**
- `PERMIT_DATE > FINAL_DATE`: **0**
- `FILE_DATE > PERMIT_DATE`: **13** — agency timezone quirk (ApplyDate late UTC vs IssueDate stored as prior calendar day at 04:00Z); not overwritten further

## Not repairable from DATA

- Inactive Void/Expired shells with no `IssueDate` remain without `PERMIT_DATE` (appropriate).
- Residual `FILE_DATE`/`PERMIT_DATE` one-day inversions are inherent to EnerGov UTC storage, not upstream mapping errors.
