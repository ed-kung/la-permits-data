# Yuba City (CA) data repair

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for Yuba City permits against the Accela Citizen Access `DATA` JSON, then wrote `agent/scripts/ca/data_repair_ca_yuba_city.py`. The sample is already high quality: status mapping was nearly correct, FILE_DATE was fully populated, and most Active/Final issuance and final dates already matched Accela workflow events. The repair fills online-issuance PERMIT_DATE gaps, completes four missing FINAL_DATE values from Passed final inspections, corrects ten FILE_DATE values that lagged Application Acceptance/Submittal by 1–5 days, and fixes five status lags (Issued→Final, Ready to Issue→Active, Voided shells→Inactive).

## Sample

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Filter: `JURISDICTION == "Yuba City"`, `STATE == "CA"`
- Records: **2,001**
- Script: `agent/scripts/ca/data_repair_ca_yuba_city.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_yuba_city_repaired.parquet`

## DATA schema

Accela portal scrape (same family as Martinez / Lake County). Top-level keys include `date`, `status`, `tasks`, `inspections`, `search_data`, `details`, `more_details`, etc.

| INFERRED_SCHEMA | n |
| --- | ---: |
| portal_issued_finaled | 1,243 |
| portal_issued | 568 |
| portal_application_only | 189 |
| portal_final_insp_only | 1 |

Canonical field sources:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status` / `search_data.Status`, with workflow overrides |
| FILE_DATE | Earliest of `DATA.date`, `search_data.Date`, Application Acceptance/Submittal Accepted* |
| PERMIT_DATE | Permit Issuance Issued; fallback Application Submittal Issued |
| FINAL_DATE | Inspection Final Inspection Complete; fallbacks: Inspections Finaled, Final CO Issued, Passed/Approved final `inspections[]` Status Date |

## Findings by field

### STATUS_NORMALIZED

Baseline distribution was already sensible (`Finaled`→Final, `Issued`→Active, `Expired`/`Void`→Inactive, review-pipeline labels→In Review; `CofO Issued`→Final). Issues found:

1. **Portal lag (2 rows):** `Issued` with dated Inspection `Final Inspection Complete` left Active while FINAL_DATE was already set → FIXED to Final.
2. **Ready to Issue with Issued (1 row):** Permit Issuance Issued present → FIXED to Active.
3. **Voided shells (2 rows):** `Issued` / `Ready to Issue` whose Permit Issuance events are all Void → FIXED to Inactive.
4. **Submitted vs STATUS_ORIGINAL=issued (1 row):** `DATA.status` says Submitted but STATUS_ORIGINAL is issued with PERMIT_DATE set and no Issued task event. STATUS_ORIGINAL keeps it Active (no demotion).
5. **Passed Final - Building alone:** ~12 Issued shells have a Passed final inspection without Accela’s Final Inspection Complete task. These stay Active; inspections[] are used only to fill FINAL_DATE on already-Final rows, not to promote status.

### FILE_DATE

Already populated for all 2,001 rows and matched `DATA.date`. Ten rows had Application Acceptance/Submittal Accepted* 1–5 days earlier than `DATA.date` → FIXED to the earlier date. Coverage remains 100%.

### PERMIT_DATE

Already matched Permit Issuance Issued whenever that event existed (1,791 exact matches, 0 mismatches). **20** Active/Final online shells used Application Submittal Issued instead of Permit Issuance and were missing PERMIT_DATE → FILLED. After repair: Active 100% coverage; Final 1,246/1,248 (99.8%). Two Finaled rows (BLD17-00419, BLD17-00336) have no Issued event anywhere → left missing.

### FINAL_DATE

Already matched Final Inspection Complete when present. **4** Finaled rows lacked FINAL_DATE but had Passed `Final - Building` inspection Status Dates → FILLED. After repair: Final 100% FINAL_DATE; non-Final statuses have none. One pre-existing chronology inversion remains (BLD17-01692: PERMIT_DATE 2018-09-05 after FINAL_DATE 2017-07-11).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 5 | 0 → 0 |
| FILE_DATE | 0 | 10 | 0 → 0 |
| PERMIT_DATE | 20 | 0 | 209 → 189 |
| FINAL_DATE | 4 | 0 | 757 → 753 |

Status transitions: Active→Final (2), In Review→Active (1), In Review→Inactive (1), Active→Inactive (1).

Ideal-coverage after repair:

- FILE_DATE: 2,001 / 2,001 (100%)
- Active PERMIT_DATE: 439 / 439 (100%)
- Final PERMIT_DATE: 1,246 / 1,248 (99.8%)
- Final FINAL_DATE: 1,248 / 1,248 (100%)
- Chronology: FILE > PERMIT = 0; PERMIT > FINAL = 1 (pre-existing)
