# South Palm Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-appearance order) was **South Palm Beach**. DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`), same family as Palm Beach Shores / North Palm Beach / Lake Clarke Shores. Upstream left all 21 `Fee Payment` rows with null `STATUS_NORMALIZED`; repair filled them to In Review. `FILE_DATE` already matched `DateCreated` on every row. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. South Palm Beach was the first pair without `agent/scripts/fl/data_repair_fl_south_palm_beach.py` (215 earlier FL jurisdictions already had scripts; Orchid remains after).

## DATA shape

721 rows. All share the same MGO key set with `PaymentProcessorModule == "MGO"` → `INFERRED_SCHEMA = mgo_ppm` (721/721).

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` (`Project Closed/Complete`→Final, `Permit Issued`→Active, `Pending (Under Review)` / `Fee Payment`→In Review) |
| FILE_DATE | `DateCreated` |
| PERMIT_DATE | `DateIssued` when not `0001-01-01` (never in sample) |
| FINAL_DATE | unavailable (no finaled / CO / completion timestamp; `DateUpdated` always sentinel) |

## Field assessments

### STATUS_NORMALIZED

Before: 21 null (`Fee Payment` unmapped). Other portal statuses already correct. Repair FILLED all 21 → In Review. After: 0 null.

| ProjectStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Permit Issued | 398 | Active | Correct |
| Project Closed/Complete | 194 | Final | Correct |
| Pending (Under Review) | 108 | In Review | Correct |
| Fee Payment | 21 | null → In Review | FILLED (pre-issuance payment step) |

### FILE_DATE

Before/after: 721/721 populated. Every `FILE_DATE` already equals `DateCreated` at calendar-day resolution (0 FILLED / FIXED).

### PERMIT_DATE

Before/after: 0 populated. Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row. No alternate issuance stamp in DATA. Active/Final coverage remains 0/592. Script will fill from a real `DateIssued` if present in future extracts.

### FINAL_DATE

Before/after: 0 populated. `DateUpdated` is likewise always the `.NET` sentinel; `RequestInspections` is a boolean flag (always False), not inspection history. Final coverage remains 0/194.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_south_palm_beach.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 21 | 0 | 21 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 721 → 721 |
| FINAL_DATE | 0 | 0 | 721 → 721 |

Post-repair coverage:

- STATUS_NORMALIZED null: 0
- FILE_DATE overall: 721/721 (100%)
- Active/Final PERMIT_DATE: 0/592 (0%) — DateIssued not published in this extract
- Final FINAL_DATE: 0/194 (0%) — no finaled/CO date in DATA
- Date order violations (FILE>PERMIT, PERMIT>FINAL, FILE>FINAL): 0

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_south_palm_beach.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_fl_south_palm_beach_repaired.parquet`
