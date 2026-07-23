# San Antonio DATA Column Repair Assessment

## Summary

Assessed the feasibility of filling missing `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` values for 2,002 San Antonio records using information extracted from the `DATA` JSON column. The repair function fills 100% of missing `FILE_DATE` values, 56.3% of `FINAL_DATE`, 54.5% of `PERMIT_DATE`, and 26.9% of `STATUS_NORMALIZED`. It also corrects 72 records misclassified as "Final" that were never actually issued (reclassified to "Inactive").

## Data Overview

| Field | Total Records | Missing | Missing % |
|-------|--------------|---------|-----------|
| STATUS_NORMALIZED | 2,002 | 52 | 2.6% |
| FILE_DATE | 2,002 | 16 | 0.8% |
| PERMIT_DATE | 2,002 | 1,701 | 85.0% |
| FINAL_DATE | 2,002 | 1,970 | 98.4% |

## DATA Column Structure

San Antonio records use an Accela Civic Platform schema with a uniform top-level structure. Key fields for extraction:

- **`date`** — top-level application/filing date (present in all 2,002 records)
- **`status`** — current permit status string (present in 1,964 records; 38 are `None`)
- **`tasks`** — list of workflow steps, each containing a `name` and `events` list with timestamps and status transitions
- **`record_type`** — classifies the permit/application type, determines which workflow applies

### Workflow Families

Three workflow families were identified, plus non-issuance record types:

- **Workflow A ("Application" records):** ~50% of records. Uses "Application Intake" → reviews → "Permit Issued" → "Closure" tasks.
- **Workflow B ("Direct Permit" records):** ~43% of records. Uses "Issuance" → "Permit Closure" tasks.
- **Workflow C ("Plat/Subdivision" records):** ~1% of records. Uses "Plat Approval Completeness Review" → "Approval Completeness" tasks.
- **Non-issuance record types:** ~6% of records. Applications, investigations, inspections, and administrative records that never go through a formal issuance step (52 distinct record types identified).

## Extraction Results

### FILE_DATE (application/submitted date)

- **Source:** `DATA.date`
- **Validation:** 1,986/1,986 = **100%** match against existing values
- **Filled:** 16/16 missing → **100%** fill rate

### PERMIT_DATE (approval/issued date)

- **Task-level extraction:**
  - Workflow A: "Permit Issued" task → first event "Marked as" "Issued"
  - Workflow B: "Issuance" task → first event "Marked as" "Active"
  - Workflow C: "Plat Approval Completeness Review" / "Approval Completeness" → first event "Marked as" "Completed"
- **Validation:** 255/286 = **89.2%** match among extractable records
  - 31 mismatches: 25 are records where the existing PERMIT_DATE was populated from a later COO/LOC issuance event rather than the initial permit issuance; 6 others follow similar COO patterns
- **Task-level fill:** 720 records

- **Non-issuance Closed record fill:** For the 52 record types that never go through issuance (applications, investigations, inspections, etc.), "Closed" status means the case was completed. Missing PERMIT_DATE is set to FILE_DATE for these records, since the entire lifecycle effectively occurs at filing.
- **Non-issuance fill:** 207 additional records

- **Combined fill:** 927 / 1,701 missing → **54.5%** fill rate
- **Unfillable records** (774) are mainly issuance-type permits with TBD issuance dates (145), permits that were never issued (72, now reclassified as Inactive), and other edge cases

### FINAL_DATE (finalized/completion/signed-off date)

- **Primary sources:**
  - Workflow A: "Closure" task → last event "Marked as" "Closed" or "Closure"
  - Workflow B: "Permit Closure" task → last event "Marked as" "Closed", "LOC Issued", "COO Issued", or "Closure"
- **Primary validation:** 5/7 = **71.4%** match (very small validation sample)
  - 2 mismatches: timing discrepancies of days/months, likely due to post-closure workflow updates
- **Primary fill:** 1,022 records

- **Fallback — fast-track inference:** For records where (a) a Closure/Permit Closure task exists but has no terminal events, and (b) `DATA.status` indicates a final state, the latest dated event across all tasks (`max_event_date`) is used as a proxy.
  - **93 Final records** have empty closure tasks. These are predominantly auto-processed MEP Trade Permits (79/93) where the entire workflow fires on a single day.
  - **Validation (same-day records):** Among 195 same-day Final records with populated closure events, `closure_date == max_event_date` in **195/195 (100%)**.
  - **Validation (multi-day records):** Among 465 multi-day Final records with populated closure events, `closure_date == max_event_date` in **458/465 (98.5%)**. The 7 exceptions have post-closure Document Review events days to weeks later.
  - **Fallback fill:** 87 additional records

- **Non-issuance Closed record fill:** Missing FINAL_DATE set to FILE_DATE for non-issuance record types with "Closed" status. All 205 such records already had their FINAL_DATE filled by the fast-track fallback (they all have Closure tasks), so this acts as a redundant safety net.

- **Combined fill:** 1,109 / 1,970 missing → **56.3%** fill rate

### STATUS_NORMALIZED

- **Source:** `DATA.status` mapped via status lookup table
- **Validation:** ~97% dominant-mapping agreement across 1,950 non-missing records
- **Status mapping** (30 distinct status values → 4 normalized categories):
  - **Active:** Issued, Active, Approved, Released
  - **Final:** Closed, LOC Issued, Completed, Case Resolved, COO Issued, Recorded, No Violation, Approved Sign-Off
  - **Inactive:** Inactive, Expired, Withdrawn, About to Expire, Revoked, Denied
  - **In Review:** Under Review, Pending Inspection, Received, Additional Info Required, Fees Due, Pending Resolution, Awaiting Renewal, Pending Issuance, Pending Yellow Investigation, Pending Red Investigation, Active Holds, Renewal In Process
- **Filled:** 14/52 missing → **26.9%** fill rate
  - 38 records have `None`/null `DATA.status` and cannot be recovered

- **Post-fill correction — never-issued permits:**
  - `DATA.status == "Closed"` is ambiguous: it can mean "successfully completed" or "administratively closed after withdrawal."  The default mapping sends all "Closed" to "Final" (98.8% dominant mapping), but 72 records have issuance-type record types yet were never actually issued — their "Permit Issued"/"Issuance" task contains "Withdrawn" or "Permit Closure" events but no "Issued"/"Active" event.
  - These 72 records are reclassified from "Final" to **"Inactive"**.
  - Breakdown: 49 MEP Trade Permits, 15 Fire Systems Permit Applications, 7 Tree Permits, 1 Tree Affidavit/Permit Application.
  - **Corrected STATUS_NORMALIZED distribution:**

| Status | Before | After | Δ |
|--------|--------|-------|---|
| Active | 824 | 826 | +2 |
| Final | 754 | 683 | −71 |
| In Review | 121 | 132 | +11 |
| Inactive | 251 | 323 | +72 |
| NaN | 52 | 38 | −14 |

## Caveats

1. **PERMIT_DATE mismatch pattern:** ~11% of records with existing PERMIT_DATE show a discrepancy where the existing value corresponds to a later COO/LOC date rather than the initial permit issuance. The repair function uses the first issuance event as the permit date, which is semantically correct but differs from the existing data for these records.

2. **FINAL_DATE small validation sample:** Only 32 of 2,002 records have existing FINAL_DATE values, providing limited validation data. The primary extraction logic is structurally sound (matching closure task events) but should be monitored.

3. **FINAL_DATE fast-track fallback:** 87 additional records are filled using `max_event_date` as a proxy when the closure task is empty but the record's status is terminal. This is strongly supported for same-day auto-processed permits (100% validated). For the small number of multi-day empty-closure records, the proxy is approximate (98.5% validated) — the 7 known exceptions involve post-closure Document Review events that slightly overshoot the true closure date.

4. **Non-issuance record types:** The set of 52 record types classified as "non-issuance" was determined empirically from the 2,002-record sample. New record types not in this set would fall through to the task-level extraction logic. The set is hardcoded and may need updating if new record types appear in future data.

5. **STATUS_NORMALIZED tentative mappings:** 8 status values (covering 14 missing records) have no ground truth for validation. Mappings were inferred from semantic similarity to validated statuses.

6. **STATUS_NORMALIZED correction scope:** The 72 never-issued corrections are gated on `DATA.status == "Closed"` (not other final statuses like "LOC Issued" or "COO Issued") and on the record type having an issuance task. This avoids false positives from record types that legitimately reach "Final" without issuance.

## Artifacts

| File | Description |
|------|-------------|
| `agent/scripts/san_antonio_data_repair.py` | Extraction functions, batch fill, status correction |
