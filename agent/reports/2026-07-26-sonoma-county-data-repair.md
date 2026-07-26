# Sonoma County data repair

**Summary:** First jurisdiction without an existing repair script in the CA sample was Sonoma County (CA). Its Accela Citizen Access `DATA` payloads are uniform (`tasks_full`). STATUS_NORMALIZED had 44 unmapped blanks plus 27 mislabels (Finished→Final, Done→In Review); FILE_DATE was already complete and correct; PERMIT_DATE gained 45 HTML-rescued issuance dates and 1 fix; FINAL_DATE gained 255 fills from Closed/Inspection/Investigate events and 4 fixes (including clearing one spurious Active final). After repair, status is fully populated, FILE_DATE remains 100%, Active PERMIT_DATE is 90.2%, and Final FINAL_DATE is 94.1%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-seen order. First pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Sonoma County, CA** (`agent/scripts/ca/data_repair_ca_sonoma_county.py`). Sample size: **2,002** rows.

## DATA schema

All 2,002 rows share one Accela key-set variant classified as `tasks_full`:

- Core: `date`, `status`, `tasks`, `search_data`, `details`, `more_details`, `record_type`, …
- Extended: `contacts`, `fees_details`, `inspections`, `conditions`, `related_records`

Dates live primarily in workflow `tasks[].events` (`Marked as` / `on`), with an HTML fallback when Accela only stores structured `Assigned to` and buries Marked-as/on in `html`. Optional fallback for issuance: `more_details['Application Information']['KEY DATES']['Date Issued From']`.

## Field assessments

### STATUS_NORMALIZED

| Before | Count |
| --- | ---: |
| Final | 1,300 |
| Inactive | 284 |
| Active | 260 |
| In Review | 114 |
| missing | 44 |

- Existing mappings from `DATA.status` were mostly correct (unique status→normalized mapping in the crosstab).
- **Missing (44):** blank `DATA.status` (22 deferred-submittal / safety shells), plus unmapped values: `Resubmittal Requested`, `Notice & Order`, `ENTERED`, `Pending Test Data`, `Referrals Sent`, `Active Permit or Plan Check`, `Complete for Processing`, `Waiting for Other Approvals`.
- **Incorrect:** `Done` (4 OTC zoning/design reviews with `Closed:Closed`) labeled In Review; `Finished` (23 legacy shells with `Inspection:Expired` / `Closed:Finished`) labeled Final — these are expired/finished-without-final, not completed finals.

### FILE_DATE

- **0 missing**; every row matches `DATA.date` at calendar-day resolution.
- No repair needed.

### PERMIT_DATE

- **613 missing** before repair.
- Among Active/Final, 334 lacked PERMIT_DATE. Primary cause for ~45 Issued/Finaled rows: Permit Issuance events present only in HTML (`Marked as Paid/Issued on …`) without structured Marked-as fields — original pipeline missed them.
- Canonical source when present: `Permit Issuance` / `Paid` or `Issued` (Sonoma uses Paid as the main issuance mark; 1,385 existing PERMIT_DATE values match this).
- Remaining Active/Final gaps are mostly non-building finals (Closed, Complete-*, Recorded, Certified, Notice & Order, Approved without issuance) with no issuance event in DATA.

### FINAL_DATE

- **1,037 missing** before; **336 of 1,300 Final** rows lacked FINAL_DATE.
- Canonical source: `Inspection` Finaled (matches 956 existing values); also `Closed` Closed/Complete/Finished, `Investigate` Complete*, `Recordation` Recorded, `Cashier` Certified.
- One Active (`Approved` Well Study) carried a spurious FINAL_DATE from Inspection Complete + Closed while status stayed Active.
- Three Final rows had FINAL_DATE earlier than the latest close-out event → corrected to latest.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_sonoma_county.py`  
Artifact: `AGENT_DATA_PATH/processed_data/permits_ca_sonoma_county_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 44 | 27 | 44 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 45 | 1 | 613 → 568 |
| FINAL_DATE | 255 | 4 | 1,037 → 783 |

Status after repair: Final 1,296 · Inactive 307 · Active 266 · In Review 133 · missing 0.

Coverage after repair:

| | Active | Final | In Review | Inactive |
| --- | ---: | ---: | ---: | ---: |
| PERMIT_DATE | 240/266 (90.2%) | 1,012/1,296 (78.1%) | 0/133 | 182/307 |
| FINAL_DATE | 0/266 | 1,219/1,296 (94.1%) | 0/133 | 0/307 |
| FILE_DATE | 2,002/2,002 (100%) | | | |

## Not repairable from DATA

- ~284 Final rows (mostly Closed / Complete-* / Recorded / Certified / safety assessments) never show a Permit Issuance event → PERMIT_DATE left missing.
- ~77 Final rows lack any dated completion/close-out event (esp. Complete - Green/Red shells with only `Investigate:TBD`) → FINAL_DATE left missing.
- 26 Active rows (Notice & Order, Approved, Issued without recoverable issuance HTML, etc.) have no issuance date in DATA.
