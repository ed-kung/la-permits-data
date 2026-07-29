# San Anselmo (CA) data repair

**Summary:** Assessed San Anselmo's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_san_anselmo.py`. San Anselmo uses a civic portal payload (`permit_info` + `search_data`). The main defect is stale `STATUS_ORIGINAL` / `STATUS_NORMALIZED` that lags `permit_info.PermitStatus`. The repair fixes 52 statuses, fills 57 PERMIT_DATEs and 17 FINAL_DATEs, and clears 1 spurious FINAL_DATE on a CANCELLED shell. After repair, FILE_DATE is 99.9% populated, Active/Final have ≥99% PERMIT_DATE, and Final has 98.8% FINAL_DATE.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **San Anselmo, CA**.

## DATA schema

All 2,000 rows have DATA with the same top-level keys: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Canonical fields live under `permit_info`. Inferred content variants:

| Schema | N | Notes |
| --- | --- | --- |
| `permit_info_issued` | 908 | Issued present, Finaled blank |
| `permit_info_issued_finaled` | 786 | Issued + Finaled present |
| `permit_info_applied_only` | 198 | only Applied populated |
| `permit_info_approved_only` | 92 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 14 | Finaled present, Issued blank |
| `permit_info_empty_dates` | 2 | status present, no usable dates |

Canonical mappings from DATA:

- `permit_info.PermitStatus` → `STATUS_NORMALIZED` (with FinaledDate / IssuedDate overrides)
- `permit_info.PermitAppliedDate` → `FILE_DATE`
- `permit_info.PermitIssuedDate` (fallback `search_data.ISSUED`, then `PermitApprovedDate`) → `PERMIT_DATE`
- `permit_info.PermitFinaledDate` (fallback: latest passed final inspection) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Active 868 / Final 806 / In Review 198 / Inactive 128 / missing 0.

Root cause: `STATUS_NORMALIZED` was derived from `STATUS_ORIGINAL`, which is often stale relative to `permit_info.PermitStatus` (29 rows differ case-insensitively). Examples: `STATUS_ORIGINAL=issued` while `PermitStatus=FINALED` / `CANCELLED` / `READY TO PAY`; `STATUS_ORIGINAL=action required` while `PermitStatus=ISSUED` / `EXPIRED` / `FINALED`.

Status map from `PermitStatus`:

| PermitStatus | → |
| --- | --- |
| FINALED, COMPLETE | Final |
| ISSUED, APPROVED | Active |
| RECEIVED, RECEIVED AND PAID, ACTION REQUIRED, READY TO PAY, INCOMPLETE, UNDER REVIEW | In Review |
| WITHDRAWN, CANCELLED, EXPIRED, VOID, REVOKED | Inactive |

Overrides (non-inactive only):

1. `PermitFinaledDate` present → Final (promotes 2 ISSUED shells that already carry a finaled stamp).
2. Pre-issuance In Review labels that already carry `PermitIssuedDate` → Active.

Repair performance: **0 FILLED, 52 FIXED**; missing after: **0**.

After: Active 895 / Final 817 / In Review 158 / Inactive 130.

Notable transitions: In Review→Active 37 (mostly ACTION REQUIRED / ISSUED / READY TO PAY with IssuedDate); Active→Final 10 (8 FINALED + 2 ISSUED-with-FinaledDate); In Review→Inactive 2 (EXPIRED); Active→Inactive 1 (CANCELLED); Inactive→Active 1 (ISSUED formerly labeled revoked).

### FILE_DATE

Before: 2 missing. Where both present, FILE_DATE matches `PermitAppliedDate` exactly (1,998/1,998).

The 2 gaps are legacy `RECEIVED` shells (`B2014-0345`, `B2014-0348`) with blank Applied/Approved/Issued/Finaled and no alternate date in `search_data` / fees / inspections.

Repair: **0 FILLED, 0 FIXED**. Coverage remains **1,998 / 2,000 (99.9%)**.

### PERMIT_DATE

Before: 316 missing. Where both present, PERMIT_DATE matches `PermitIssuedDate` exactly (1,684/1,684). Ten ISSUED rows (status lagged as In Review/Inactive) had IssuedDate but null PERMIT_DATE; 102 rows had Approved but no Issued/PERMIT.

Repair: **57 FILLED, 0 FIXED** — fills Issued (and Approved fallback) on Active/Final after status correction.

Remaining Active/Final gap: **13** (9 Active APPROVED/ISSUED shells and 4 FINALED shells with neither Issued nor Approved in DATA). After repair: Active **886 / 895 (99.0%)**; Final **813 / 817 (99.5%)**.

### FINAL_DATE

Before: 1,209 missing. Where both present, FINAL_DATE matches `PermitFinaledDate` (791/791). Nine FINALED rows had FinaledDate but null FINAL_DATE because status was still Active/In Review. Three non-Final rows carried FINAL_DATE (2 ISSUED-with-FinaledDate; 1 CANCELLED close stamp).

Repair: **17 FILLED** (9 from PermitFinaledDate on status-promoted Finals; 8 from passed final inspections), **1 FIXED** (cleared CANCELLED `ENC2016-0060` close stamp). The two ISSUED+FinaledDate shells were promoted to Final, so their FINAL_DATE is retained as correct.

Final coverage after repair: **807 / 817 (98.8%)**. Remaining 10 FINALED/COMPLETE shells lack both FinaledDate and a usable final inspection. No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_san_anselmo.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 52 | 0 | 0 |
| FILE_DATE | 0 | 0 | 2 | 2 |
| PERMIT_DATE | 57 | 0 | 316 | 259 |
| FINAL_DATE | 17 | 1 | 1,209 | 1,193 |

### Coverage after repair

| Metric | Value |
| --- | --- |
| FILE_DATE populated | 1,998 / 2,000 (99.9%) |
| Active PERMIT_DATE | 886 / 895 (99.0%) |
| Final PERMIT_DATE | 813 / 817 (99.5%) |
| Final FINAL_DATE | 807 / 817 (98.8%) |
| Spurious FINAL on non-Final | 0 |

### Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_san_anselmo.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_san_anselmo_repaired.parquet`
