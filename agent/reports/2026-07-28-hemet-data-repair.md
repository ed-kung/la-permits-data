# Hemet (CA) data repair

**Summary:** Hemet was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the civic-portal `DATA` JSON (`permit_info` + `inspections`). Status missingness fell from **19 → 0** (**FILLED 19 · FIXED 49**): unmapped `CREATED IN ERROR` / `OUT TO OWNER` / `SIGNATURE REQUIRED` filled; Finaled/Active/Expired/Refunded/Pending mismatches and FinaledDate overrides corrected. `FILE_DATE` already matched `PermitAppliedDate` wherever Applied exists (**FILLED 0 · FIXED 0**); 1 VOID shell lacks Applied. `PERMIT_DATE` gained **FILLED 58** (mostly Approved fallback when Issued blank). `FINAL_DATE` gained **FILLED 36 · FIXED 3** (PermitFinaledDate + final inspections; cleared spurious finals on Inactive EXPIRED). Final coverage is **1,382 / 1,436 (96.2%)**. Active PERMIT coverage is **281 / 313 (89.8%)**.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Hemet, CA** (n=2,001) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` (index 88 after Mendocino County)
- Script: `agent/scripts/ca/data_repair_ca_hemet.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_hemet_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Canonical dates/status live under `permit_info`; `search_data` only mirrors Address / RECORDID / Permit #. Sub-schemas reflect which `permit_info` dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,351 | Issued + Finaled present |
| `permit_info_issued` | 443 | Issued present, Finaled blank |
| `permit_info_applied_only` | 125 | Only Applied populated |
| `permit_info_approved_only` | 54 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 27 | Finaled present, Issued blank |
| `permit_info_empty_dates` | 1 | Status text, no usable dates (VOID shell) |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus`; else FinaledDate → Final (non-inactive); else blank-status date inference |
| `FILE_DATE` | `PermitAppliedDate` only (do not backfill from Issued) |
| `PERMIT_DATE` | `PermitIssuedDate`; else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest final / C of O inspection |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,392 · Active 350 · Inactive 167 · In Review 73 · missing 19

`PermitStatus` → expected mapping:

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, CLOSED | Final |
| ACTIVE | Active |
| PENDING, FEES DUE, ONLINE, INCOMPLETE SUBMITTAL, CORRECTIONS, PLAN REVIEW, OUT TO OWNER, SIGNATURE REQUIRED | In Review |
| EXPIRED, EXPIRED-RENEWED, CREATED IN ERROR, DENIED, REFUNDED | Inactive |

Additionally, non-inactive rows with `PermitFinaledDate` present are treated as **Final** (portal status lagged behind finalization).

Issues:
1. **19 null `STATUS_NORMALIZED`:** unmapped upstream → **FILLED** Inactive (16 `CREATED IN ERROR`) or In Review (2 `OUT TO OWNER`, 1 `SIGNATURE REQUIRED`).
2. **49 mismatches (FIXED):**
   - FINALED labeled Active (25) or In Review (2) — STATUS_ORIGINAL often `active` / `fees due` / `plan review`
   - ACTIVE with FinaledDate labeled Active → Final (10)
   - PENDING with FinaledDate labeled In Review → Final (7)
   - REFUNDED labeled Active → Inactive (2)
   - EXPIRED labeled Active/In Review → Inactive (2)
   - ACTIVE labeled In Review → Active (1)

**After:** Final 1,436 · Active 313 · Inactive 187 · In Review 65 · missing 0  
Flags: **FILLED 19 · FIXED 49**

### FILE_DATE

**Before:** 1 missing (0.05%).

- Wherever `PermitAppliedDate` exists (2,000 rows), `FILE_DATE` matches exactly — 0 disagreements.
- The 1 missing row (`E2007-031`) is a VOID shell (`PermitType=VOID`, `PermitStatus=ACTIVE`) with blank Applied/Issued/Approved/Finaled. Not backfilled from Issued (none present).

**After:** still 1 missing.  
Flags: **FILLED 0 · FIXED 0**  
Coverage: **2,000 / 2,001 (99.95%)**.

### PERMIT_DATE

**Before:** 210 missing (10.5%). Among Active/Final: 102 / 1,742 missing (Active 55/350 · Final 47/1,392).

- When set, `PERMIT_DATE` always matched `PermitIssuedDate` (1,791/1,791) — 0 incorrect values to fix against Issued.
- **FILLED 58:** 3 from `PermitIssuedDate` on status-fixed Active/Final rows that previously lacked PERMIT; **55** from `PermitApprovedDate` when Issued blank (common on applied/approved shells and some Finaled-without-Issued records).

Gaps after repair (152 overall; Active 32 · Final 19 still missing) are dominated by:
- **`permit_info_applied_only`** Active (31) / Final (10): no Issued or Approved in DATA.
- **`permit_info_finaled_only`** Final (9): Finaled present, neither Issued nor Approved.
- 1 VOID empty-dates shell.

**After:** missing 152.  
Flags: **FILLED 58 · FIXED 0**  
Active coverage: **281 / 313 (89.8%)** · Final coverage: **1,417 / 1,436 (98.7%)**

### FINAL_DATE

**Before:** 652 missing (32.6%); Final missing 63 / 1,392. When present, always matched `PermitFinaledDate` (1,349/1,349).

- **FILLED 36:** 29 from `PermitFinaledDate` (mostly status-fixed Final rows that already had FinaledDate but missing `FINAL_DATE`); **7** from inspections (`FINAL**` / `FINAL-FIRE` / `MONUMENT FINAL` / `CERTIFICATE OF OCCUP` with APPROVED/FINALED/empty result).
- **FIXED 3:** cleared spurious `FINAL_DATE` on Inactive (`EXPIRED`) rows that still carried `PermitFinaledDate`.
- Remaining Final gaps: **54** (`FINALED` 50 · `CLOSED` 4) with blank FinaledDate and no usable final inspection (`permit_info_issued` 30 · `approved_only` 14 · `applied_only` 10).

**After:** missing 619; Final coverage **1,382 / 1,436 (96.2%)**.  
Flags: **FILLED 36 · FIXED 3**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 19 | 49 | 19 → 0 |
| `FILE_DATE` | 0 | 0 | 1 → 1 |
| `PERMIT_DATE` | 58 | 0 | 210 → 152 |
| `FINAL_DATE` | 36 | 3 | 652 → 619 |

Coverage after repair:

| Metric | Value |
| --- | --- |
| Active with `PERMIT_DATE` | 281 / 313 (89.8%) |
| Final with `PERMIT_DATE` | 1,417 / 1,436 (98.7%) |
| Final with `FINAL_DATE` | 1,382 / 1,436 (96.2%) |
| All with `FILE_DATE` | 2,000 / 2,001 (99.95%) |

Chronology notes (source DATA, not introduced by repair): 25 rows with `PERMIT_DATE` < `FILE_DATE` (Issued/Approved earlier than Applied in portal); 4 with `FINAL_DATE` < `PERMIT_DATE` (re-issuance after earlier final, or Approved fallback after FinaledDate).
