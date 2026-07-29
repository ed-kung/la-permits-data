# San Buenaventura (CA) data repair

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for San Buenaventura permits against the Tyler EnerGov `DATA` JSON, then wrote `agent/scripts/ca/data_repair_ca_san_buenaventura.py`. Most rows already matched `entity` dates; the main defects were STATUS_ORIGINAL lagging behind live `CaseStatus` (Final/Expired/Issued/Cancelled), 62 unmapped `Other - See Comments` statuses, Approved-without-issuance labeled Active, and junk FINAL_DATE stamps on non-Final rows. After repair: status complete; FILE_DATE 100%; Active PERMIT_DATE 100%; Final PERMIT_DATE 99.9% / FINAL_DATE 100%.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **San Buenaventura, CA**.

## Sample

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Filter: `JURISDICTION == "San Buenaventura"`, `STATE == "CA"`
- Records: **2,000**
- Script: `agent/scripts/ca/data_repair_ca_san_buenaventura.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_san_buenaventura_repaired.parquet`

## DATA schema

Tyler EnerGov-style payload (same family as Upland / Rancho Cordova). Top-level keys are always `fees`, `entity`, `details`, `contacts`, `processing_status`, with an optional reviews bundle. `processing_status` is null for every sample row.

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_fees | 1,786 |
| entity_fees_reviews | 214 |

Canonical field sources:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` / `details.PermitStatus`, with IssueDate / FinalDate overrides |
| FILE_DATE | `entity.ApplyDate` (details fallback) |
| PERMIT_DATE | `entity.IssueDate` (details fallback) |
| FINAL_DATE | `entity.FinalDate` (fallback `details.FinalizeDate`; inspection fallback unused here) |

City-specific CaseStatus labels include `Deposit Fees Due` / `Deposit Fees Paid`, `Returned to Applicant`, `Other - See Comments`, and `Revision Issued`.

## Findings by field

### STATUS_NORMALIZED

Before: Final 722; Inactive 452; Active 440; In Review 324; missing 62.

STATUS_NORMALIZED was driven by STATUS_ORIGINAL, which lagged live `CaseStatus` on 66 rows. Issues repaired:

1. **Missing status (62):** 59 `Other - See Comments` → FILLED In Review; 3 `Issued` shells whose STATUS_ORIGINAL was still `other - see comments` → FILLED Active.
2. **In Review → Active (22):** `Issued` / `Revision Issued` (and a few Fees Due/Paid / Stop Work with IssueDate) left In Review because STATUS_ORIGINAL lagged → FIXED to Active.
3. **Active → Final (17):** 13 `Final` + 1 `Complete` left Active (`STATUS_ORIGINAL=issued`); 3 `Issued` with FinalDate strictly after IssueDate → FIXED to Final.
4. **Active → Inactive (9):** `Expired` / `Cancelled` left Active (`STATUS_ORIGINAL=issued`) → FIXED to Inactive.
5. **Active → In Review (5):** `Approved` GRIM* shells with no IssueDate were incorrectly Active → FIXED to In Review.
6. **In Review → Inactive (3):** `Expired` / `Cancelled` left In Review → FIXED to Inactive.
7. **Inactive → Final (1):** `Final` CaseStatus left Inactive (`STATUS_ORIGINAL=expired`) → FIXED to Final.
8. **In Review → Final (1):** review-pipeline shell with credible FinalDate → FIXED to Final.

Inactive labels (Expired / Cancelled / Denied / Plan Approval Expired) stay sticky even when FinalDate is a case-closure stamp. Issued shells with FinalDate ≤ IssueDate stay Active.

### FILE_DATE

Already populated for all 2,000 rows and matches `entity.ApplyDate` at calendar-day resolution (0 mismatches). No repairs. Five source chronology quirks remain where ApplyDate is one calendar day after IssueDate (overnight UTC ApplyDate vs date-truncated IssueDate); both dates match DATA, so left as-is.

### PERMIT_DATE

Existing PERMIT_DATE always matched IssueDate when both present (0 mismatches). Gaps filled:

- Active/Final shells missing PERMIT_DATE while IssueDate present (**20**) → FILLED (includes Issued promotions from In Review / missing status, plus one Active Issued gap `OVER-11-24-1003`).

Remaining Active/Final gap after repair (**1**): `WBFP-03-22-0062` (CaseStatus Final, null IssueDate) — not fillable.

After repair: Active 434/434 (100%); Final 740/741 (99.9%). In Review PERMIT_DATE coverage is 0% by design.

### FINAL_DATE

All 722 baseline Final rows already had FINAL_DATE matching FinalDate. Issues:

1. **FILLED (15):** FinalDate/FinalizeDate on rows promoted to Final that previously lacked FINAL_DATE.
2. **FIXED / cleared (16):** junk FINAL_DATE on rows that stay non-Final (Cancelled / Plan Approval Expired / Returned to Applicant / Fees Due / Issued with inverted or same-day FinalDate stamps).

After repair: Final FINAL_DATE 741/741 (100%); non-Final FINAL_DATE 0. Seven Final rows retain PERMIT_DATE > FINAL_DATE inversions present in EnerGov IssueDate/FinalDate; left as-is.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 62 | 58 | 62 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 20 | 0 | 451 → 431 |
| FINAL_DATE | 15 | 16 | 1,258 → 1,259 |

Status transitions: nan→In Review (59), In Review→Active (22), Active→Final (17), Active→Inactive (9), Active→In Review (5), nan→Active (3), In Review→Inactive (3), Inactive→Final (1), In Review→Final (1).

Ideal-coverage after repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- Active PERMIT_DATE: 434 / 434 (100%)
- Final PERMIT_DATE: 740 / 741 (99.9%)
- Final FINAL_DATE: 741 / 741 (100%)
- Chronology: FILE > PERMIT = 5 (source); PERMIT > FINAL = 7 (source)
