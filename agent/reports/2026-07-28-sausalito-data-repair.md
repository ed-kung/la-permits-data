# Sausalito (CA) data repair

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for Sausalito permits against the civic-portal `DATA` JSON, then wrote `agent/scripts/ca/data_repair_ca_sausalito.py`. Existing dates already matched `permit_info` when present; defects were STATUS_ORIGINAL lagging live `PermitStatus`, 64 blank-status legacy shells, ISSUED/CCTV rows that already carried `PermitFinaledDate` left non-Final, and Active/Final gaps fillable from Issued/Approved or final inspections. After repair: status 99.9% complete; Active PERMIT_DATE 99.8%; Final FINAL_DATE 83.7% (remaining gaps are mostly CONVERTED sewer laterals with no dates).

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Sausalito, CA**.

## Sample

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Filter: `JURISDICTION == "Sausalito"`, `STATE == "CA"`
- Records: **2,000**
- Script: `agent/scripts/ca/data_repair_ca_sausalito.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_sausalito_repaired.parquet`

## DATA schema

Civic portal payload (same family as Mill Valley / Hillsborough). Top-level keys are always `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Canonical fields live under `permit_info`.

| INFERRED_SCHEMA | n |
| --- | ---: |
| permit_info_issued | 1,243 |
| permit_info_issued_finaled | 293 |
| permit_info_applied_only | 276 |
| permit_info_approved_only | 86 |
| legacy_no_status | 61 |
| permit_info_finaled_only | 36 |
| permit_info_empty_dates | 5 |

Canonical field sources:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus`, with Finaled / Issued overrides |
| FILE_DATE | `permit_info.PermitAppliedDate` |
| PERMIT_DATE | `permit_info.PermitIssuedDate` (fallback `PermitApprovedDate`) |
| FINAL_DATE | `permit_info.PermitFinaledDate` (fallback passed final inspection) |

City-specific labels include `CCTV FAIL` / `CCTV PASS`, `CONVERTED`, `EP NOT REQUIRED`, `RESPONSE SENT TO APP`, `APPROVE PEND PAYMENT`, and `REV UNDER REVIEW`.

## Findings by field

### STATUS_NORMALIZED

Before: Active 1,231; Final 362; In Review 214; Inactive 129; missing 64.

STATUS_NORMALIZED was driven by STATUS_ORIGINAL, which lagged live `PermitStatus` on a subset of rows. Issues repaired:

1. **Missing status (61 FILLED):** 52 blank-status shells with Applied only → In Review; 9 with Issued → Active. Three blank-status shells with neither Applied nor Issued stay missing.
2. **In Review → Final (19):** 16 `CCTV FAIL` + 1 `CCTV PASS` + 2 `FINALED` that already carry `PermitFinaledDate` (STATUS_ORIGINAL lagged: waiting for payment / approve pend payment) → FIXED to Final.
3. **Active → Final (17):** 15 `ISSUED` + 2 `FINALED` with `PermitFinaledDate` left Active → FIXED to Final.
4. **In Review → Active (9):** `ISSUED` / `REV UNDER REVIEW` / `ON HOLD` / `AWAITING RESUBMITTAL` / `UNDER REVIEW` shells that already carry Issued (STATUS_ORIGINAL lagged) → FIXED to Active.
5. **In Review → Inactive (2):** `NOT APPROVED` left In Review → FIXED to Inactive.
6. **Inactive → Final (1):** `FINALED` left Inactive (`STATUS_ORIGINAL=expired`) → FIXED to Final.

Inactive labels (Expired / Void / Withdrawn / Cancelled / Not Approved) stay sticky even when Finaled is a case-closure stamp.

### FILE_DATE

Already matches `PermitAppliedDate` at calendar-day resolution whenever Applied is present (1,139/1,139; 0 mismatches). No repairs. **861** shells lack any application date in DATA (mostly ISSUED without Applied) and stay missing (57.0% coverage).

### PERMIT_DATE

Existing PERMIT_DATE always matched Issued when both present (0 mismatches). Gaps filled:

- Active/Final missing PERMIT_DATE while Issued or Approved present (**21**) → FILLED (10 APPROVED encroachment/zoning shells, several FINALED with Approved only, a few ISSUED with Issued present but PERMIT_DATE null).

After repair: Active 1,229/1,232 (99.8%); Final 313/399 (78.4%). Final gaps are dominated by 56 `CONVERTED` sewer-lateral shells plus FINALED/EP NOT REQUIRED rows with neither Issued nor Approved. In Review PERMIT_DATE coverage is 0% by design. 45 PERMIT &lt; FILE inversions exist in source Issued/Applied dates; left as-is.

### FINAL_DATE

Existing FINAL_DATE always matched Finaled when both present (0 mismatches). Issues:

1. **FILLED (11):** 5 FinaledDate fills on rows promoted/kept Final that previously lacked FINAL_DATE; 6 from passed final inspections on FINALED shells with blank FinaledDate.
2. **FIXED / cleared (1):** junk FINAL_DATE on a WITHDRAWN (Inactive) row.

After repair: Final FINAL_DATE 334/399 (83.7%); non-Final FINAL_DATE 0. Remaining Final gaps are mostly CONVERTED shells and FINALED rows with neither FinaledDate nor a usable final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 61 | 48 | 64 → 3 |
| FILE_DATE | 0 | 0 | 861 → 861 |
| PERMIT_DATE | 21 | 0 | 460 → 439 |
| FINAL_DATE | 11 | 1 | 1,676 → 1,666 |

Post-repair coverage targets:

| Metric | Coverage |
| --- | --- |
| STATUS_NORMALIZED non-null | 1,997 / 2,000 (99.9%) |
| FILE_DATE | 1,139 / 2,000 (57.0%) |
| Active PERMIT_DATE | 1,229 / 1,232 (99.8%) |
| Final PERMIT_DATE | 313 / 399 (78.4%) |
| Final FINAL_DATE | 334 / 399 (83.7%) |
