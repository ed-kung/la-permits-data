# Novato (CA) data repair — 2026-07-28

Novato was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` already has correct `FILE_DATE` and, when populated, correct `PERMIT_DATE` / `FINAL_DATE` matching `permit_info`. Main issues were unmapped / stale `STATUS_NORMALIZED` (34 missing, 8 wrong vs `PermitStatus`), missing `PERMIT_DATE` on Active/Final rows that only carry `PermitApprovedDate` (especially PERFORMED/CLOSED resales), and 7 Final rows missing `FINAL_DATE` after stale ISSUED/PENDING status. Repair fills/fixes 40 statuses, 76 permit dates, and 11 final dates; residual gaps are mostly resale/complete shells without issuance or finaled timestamps.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Novato, CA** → `agent/scripts/ca/data_repair_ca_novato.py` (n=2,000).

## DATA schema

All rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate`, `PermitApprovedDate`, `PermitFinaledDate`); `search_data.STATUS` / `APPLIED` mirror status and applied date. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,156 | Issued + Finaled present |
| `permit_info_issued` | 477 | Issued present, Finaled blank |
| `permit_info_applied_only` | 216 | Only Applied populated |
| `permit_info_approved_only` | 101 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 32 | Finaled present, Issued blank |
| `legacy_no_status` | 16 | Blank `PermitStatus`, dates present |
| `permit_info_empty_dates` | 2 | Status/type text, no usable dates |

## Field assessment

### STATUS_NORMALIZED

- Missing on 34 / 2,000 (1.7%): 14 `info or fee req`, 2 `plan chk in progress` (unmapped upstream), 18 blank `PermitStatus`.
- When `STATUS_ORIGINAL` matches `DATA.permit_info.PermitStatus`, existing normalization is consistent (FINALED/CLOSED/COMPLETE/PERFORMED → Final; ISSUED/REISSUED/APPROVED/ACTIVE → Active; review statuses → In Review; EXPIRED/INACTIVE/WITHDRAWN/VOID/REFUNDED/DENIED → Inactive; UNLOCK → In Review).
- **Issue:** 10 rows where `STATUS_ORIGINAL` lagged `PermitStatus` (e.g. `issued`/`pending` while DATA is `FINALED`; `tech review complete` / `info or fee req` / `plan chk in progress` while DATA is `ISSUED`), leaving 8 wrong `STATUS_NORMALIZED` values and 2 nulls that should be Active.
- **Repair:** map from `PermitStatus` (plus Final override when non-inactive `PermitFinaledDate` present; blank-status inference from Issued/Approved → Active, Applied → In Review) → **32 FILLED**, **8 FIXED**. Missing after: 2 (empty encroachment shells with no status or dates).

### FILE_DATE

- Missing on 5 / 2,000 (0.2%). Present values match `PermitAppliedDate` on all 1,995 rows with Applied populated.
- The 5 gaps also lack `search_data.APPLIED`; no safe application date in `DATA`.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 99.8%.

### PERMIT_DATE

- Missing on 362 / 2,000 (18.1%). When present, every value matches `PermitIssuedDate` (0 incorrect).
- Among Active/Final before repair: Active 131/152 present, Final 1,149/1,274 present.
- Recoverable gaps are mostly Final PERFORMED/CLOSED (and a few FINALED) with blank Issued but populated `PermitApprovedDate`, plus a handful of Active ISSUED/APPROVED with Issued or Approved available.
- **Repair:** **76 FILLED**, **0 FIXED**. Missing after: 286.
- Post-repair Active PERMIT coverage: 143/158 (90.5%); Final: 1,225/1,280 (95.7%). Remaining Active/Final gaps lack both Issued and Approved in `DATA`.

### FINAL_DATE

- Missing on 819 / 2,000 (41.0%). When present, every value matches `PermitFinaledDate` (0 incorrect vs that field).
- Among Final before repair: 1,177/1,274 had `FINAL_DATE`. Seven Final-after-repair rows had `PermitFinaledDate` but null `FINAL_DATE` — six because status was still Active/In Review from stale `STATUS_ORIGINAL`.
- Four non-Final rows (REFUNDED/INACTIVE) carried a spurious `FINAL_DATE` equal to a close/refund timestamp → cleared.
- Fallback to passed `**FINAL*` inspections adds no fills here (the two FINALED rows without `PermitFinaledDate` lack a passed final inspection).
- **Repair:** **7 FILLED**, **4 FIXED** (clears). Missing after: 816.
- Post-repair Final FINAL coverage: 1,184/1,280 (92.5%). Remaining Final gaps are almost all PERFORMED (61) / CLOSED (31) resale reports plus 3 FINALED / 1 COMPLETE without a finaled timestamp.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 32 | 8 | 34 | 2 |
| FILE_DATE | 0 | 0 | 5 | 5 |
| PERMIT_DATE | 76 | 0 | 362 | 286 |
| FINAL_DATE | 7 | 4 | 819 | 816 |

Status distribution after repair: Final 1,280 · Inactive 494 · Active 158 · In Review 66 · missing 2.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | ~100% | 90.5% | 0% |
| Final | ~100% | 95.7% | 92.5% |
| In Review | ~100% | 13.6% | 0% |
| Inactive | ~100% | 68.2% | 0% |

Chronology: 3 `PERMIT < FILE` and 9 `FINAL < PERMIT` cases remain; all mirror inverted dates already present in `permit_info` (not introduced by repair).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_novato.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_novato_repaired.parquet`
