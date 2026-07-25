# San Joaquin County data repair

**Summary:** First CA-sample jurisdiction without an existing repair script was San Joaquin County (1,999 rows). DATA has two schemas: Accela Citizen Access `tasks_full` (1,744) and a flatter `flat_legacy` export (255). Main defects: 588 unmapped Accela statuses (Active billable, Closed - Released, Mailed, etc.); one Closed - Permit Issued mislabeled Active; FINAL_DATE often earlier than the latest Permit Complete / Final inspection; three spurious finals on Active Inspection Phase rows. FILE_DATE was already complete and correct. Script: `agent/scripts/data_repair_ca_san_joaquin_county.py`. Artifact: `$AGENT_DATA_PATH/processed_data/permits_ca_san_joaquin_county_repaired.parquet`.

## Sample and schemas

| INFERRED_SCHEMA | n |
| --- | ---: |
| tasks_full | 1,744 |
| flat_legacy | 255 |

**tasks_full** useful fields: `DATA.status`, `DATA.date` / `search_data['Date']`, workflow `tasks[].events` (`Marked as`, `on` — keys often have trailing spaces), and `inspections[].Status Date` for Final-titled approvals.

**flat_legacy** useful fields: `Status`, `Initialized`, `Issued`, `Last Inspection` (format `MM/DD/YYYY: Approved (...)`).

## STATUS_NORMALIZED

Upstream normalization covered common Accela labels (Closed - Complete, Permit Issued, FINISHED, etc.) but left **588** rows null — mostly Environmental Health / assessment / release statuses never mapped.

| Issue | Action |
| --- | --- |
| 269 `Active, billable` (+ 1 exempt) | FILLED → Active |
| 89 `Closed - Released` | FILLED → Final |
| 70 `Inactive, non-billable` + 14 `Inactive code` | FILLED → Inactive |
| 69 Mailed / Certified Mailed / Certified and Regular Mail | FILLED → In Review |
| 17 `Billing Complete` | FILLED → Final |
| 8 Closed Entered/Initiated in Error | FILLED → Inactive |
| 4 `Other Approved Class` + 2 `EHD Class Comp` | FILLED → Final |
| 2 `Diversion Plan Approved` | FILLED → Active |
| 1 `Planning Pre-Review` | FILLED → In Review |
| 1 `Closed - Permit Issued` labeled Active | FIXED → Final |
| 40 `NONE` + 1 `UNKNOWN STATUS` + 1 blank status | left missing (historical shells) |

**Repair:** FILLED 546, FIXED 1. Missing 588 → 42.

Flat-legacy statuses (`FINAL`, `ISSUED`, `EXPIRED`, etc.) were already correct.

## FILE_DATE

Already populated for all 1,999 rows. Accela `DATA.date` and flat `Initialized` matched `FILE_DATE` exactly. No FILLED/FIXED.

## PERMIT_DATE

Ideal: present for Active and Final. Before repair, 462 of 809 already-labeled Active/Final Accela rows lacked a permit date; every one of those also lacked a dated `Permit Issuance` / `Issued` event (legacy Closed/FINISHED shells and EH Active billable records with empty workflows). Where an Issued event existed, current `PERMIT_DATE` already matched.

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 7 | Newly mapped `Closed - Released` → Final, from Application Intake / Clearance Approved |
| FIXED | 0 | — |

Remaining Active/Final missing PERMIT_DATE after repair: **839** (dominated by Active billable 269, Active 141, FINISHED 132, Closed 110, Closed - Released without clearance event 82).

Coverage after repair: Active 163/586 (27.8%), Final 422/838 (50.4%). Flat-legacy Active/Final already had Issued dates where present.

## FINAL_DATE

Ideal: present for Final. Existing Accela finals usually matched `Inspection` / `Permit Complete`; 7 used the earlier `Final Inspection Complete` when a later Permit Complete existed → FIXED to latest. 3 Active Inspection Phase rows carried a spurious FINAL_DATE from `Releases Complete` / `Complete` → cleared.

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 76 | Permit Complete / Final Inspection Complete; Final-titled approved inspections; Application Review / Completed; Final Review / Released; * Status / Closed |
| FIXED (date → latest completion) | 9 | Align to latest Permit Complete or Final inspection Status Date |
| FIXED (cleared on non-Final) | 3 | Active Inspection Phase |

Remaining Final without FINAL_DATE: **442** (FINISHED 132, Closed 104, Closed - Released without Released event 80, Closed - Complete shells 52, etc.) — overwhelmingly Accela rows with empty/TBD workflow and no Final inspection Status Date. One flat Final has empty `Last Inspection`.

Coverage after repair: Final 396/838 (47.3%); Active / In Review / Inactive all 0% (spurious finals cleared).

## Performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 546 | 1 | 588 → 42 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 7 | 0 | 1,385 → 1,378 |
| FINAL_DATE | 76 | 12 | 1,676 → 1,603 |

## Why remaining gaps persist

1. **Unmapped historical shells.** Forty `NONE` Facility Miscellaneous Transaction Historical rows (and one UNKNOWN STATUS) have blank workflow and no usable status signal.
2. **Environmental Health Active billable / Inactive non-billable.** These program permits/service requests rarely carry Permit Issuance or Inspection completion events in the Accela scrape, so dates cannot be recovered from DATA.
3. **Legacy Closed / FINISHED migrations.** Many pre-~2015 building and code records advanced listing status to Closed/FINISHED/Compliant without storing dated Issued or Permit Complete events (inspections list sometimes helps for Closed - Complete / Final Inspection Complete — those were filled when present).
4. **Release and billing stubs.** Most Closed - Released and Billing Complete rows have only TBD task events; only a handful expose Clearance Approved / Released dates.

**Bottom line:** San Joaquin County mixes a modern Accela building/EH workflow with a smaller flat legacy export. Status coverage improves a lot once billable/release/mailed labels are mapped; date gaps are mostly agency-side empty workflows rather than wrong mappings. Flat-legacy rows were largely correct already.
