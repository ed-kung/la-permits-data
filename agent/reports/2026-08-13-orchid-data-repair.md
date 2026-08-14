# Orchid (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-appearance order) was **Orchid**. DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`), same family as South Palm Beach / Lake Clarke Shores. Upstream mislabeled one `Pending (Under Review)` row as Active; repair FIXED it to In Review. `FILE_DATE` already matched `DateCreated` on every row. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: STATUS fully populated and aligned with DATA; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Orchid was the first pair without `agent/scripts/fl/data_repair_fl_orchid.py` (215 earlier FL jurisdictions already had scripts).

## DATA shape

439 rows. All share the same MGO key set with `PaymentProcessorModule == "MGO"` → `INFERRED_SCHEMA = mgo_ppm` (439/439).

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` (`Project Closed/Complete`→Final, `Permit Issued`→Active, `Pending (Under Review)`→In Review) |
| FILE_DATE | `DateCreated` |
| PERMIT_DATE | `DateIssued` when not `0001-01-01` (never in sample) |
| FINAL_DATE | unavailable (no finaled / CO / completion timestamp; `DateUpdated` always sentinel) |

## Field assessments

### STATUS_NORMALIZED

Before: 0 null. One row incorrect vs DATA. Repair FIXED 1 → In Review. After: 0 null.

| ProjectStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Permit Issued | 202 | Active | Correct |
| Project Closed/Complete | 196 | Final | Correct |
| Pending (Under Review) | 40 | In Review | Correct |
| Pending (Under Review) | 1 | Active → In Review | FIXED (ProjectNumber 2024-225; STATUS_ORIGINAL was `permit issued` but ProjectStatusID 6720 matches Pending) |

### FILE_DATE

Before/after: 439/439 populated. Every `FILE_DATE` already equals `DateCreated` at calendar-day resolution (0 FILLED / FIXED).

### PERMIT_DATE

Before/after: 0 populated. Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row. No alternate issuance stamp in DATA. Active/Final coverage remains 0/398. Script will fill from a real `DateIssued` if present in future extracts.

### FINAL_DATE

Before/after: 0 populated. `DateUpdated` is likewise always the `.NET` sentinel; `RequestInspections` is a boolean flag (always False), not inspection history. Final coverage remains 0/196.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_orchid.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 439 → 439 |
| FINAL_DATE | 0 | 0 | 439 → 439 |

Post-repair coverage:

- STATUS_NORMALIZED null: 0 (Active 202 / Final 196 / In Review 41)
- FILE_DATE overall: 439/439 (100%)
- Active/Final PERMIT_DATE: 0/398 (0%) — DateIssued not published in this extract
- Final FINAL_DATE: 0/196 (0%) — no finaled/CO date in DATA
- Date order violations (FILE>PERMIT, PERMIT>FINAL, FILE>FINAL): 0

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_orchid.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_fl_orchid_repaired.parquet`
