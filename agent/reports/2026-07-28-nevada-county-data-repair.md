# Nevada County data repair

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for Nevada County (CA) Accela permits (n=2,000), then implemented `agent/scripts/ca/data_repair_ca_nevada_county.py`. FILE_DATE was already correct for all rows. Status needed 11 fixes (About to Expire → Active, plan-check expiry → In Review, Issued+Finaled → Final, Received mislabeled Active → In Review, In Review with Issued events → Active). PERMIT_DATE gained 113 fills from ASI Issue Date plus 1 spurious clear; FINAL_DATE gained 513 fills from Final* PASS inspections and 8 fixes to the latest Inspection Finaled mark. After repair: FILE_DATE 100%, Active PERMIT_DATE 99.5%, Final FINAL_DATE 95.0%; ~462 Final rows still lack a recoverable issuance date.

## Data shape

Nevada County `DATA` is an Accela Citizen Access scrape. 1,999 rows share the full key set (`date`, `status`, `tasks`, `inspections`, `search_data`, `more_details`, …); one sparse row omits optional blocks (`accela_partial_other_events`).

INFERRED_SCHEMA counts after repair:

| Schema | n |
| --- | ---: |
| accela_full_issued_finaled | 1,016 |
| accela_full_finaled_only | 414 |
| accela_full_issued | 319 |
| accela_full_other_events | 250 |
| accela_partial_other_events | 1 |

## Field assessment

### STATUS_NORMALIZED

Upstream mapping from `DATA.status` / `STATUS_ORIGINAL` was mostly right (`Finaled`/`CLOSED`/`Closed`→Final, `Issued`→Active, `Expired`/`Void`→Inactive, `Received`/`In Review`/`Ready to Issue`/`Hold`→In Review).

Issues found:

- **About to Expire** (7) left Inactive despite Ready-to-Issue Issued evidence → should be Active.
- **Plan Check About to Expire** (1) left Inactive → In Review.
- **Received** (1) left Active via `STATUS_ORIGINAL=issued` while tasks show no issuance and `DATA.status=Received` → In Review.
- **In Review** (1) with multiple Ready-to-Issue Issued marks → Active.
- **Issued** (1) with Inspections Finaled → Final.
- **5 null** `Add a contractor` shells have empty `DATA.status` and no issuance/final evidence → left null.

### FILE_DATE

Already populated for all 2,000 rows and identical to `DATA.date` / `search_data.Date`. No fills or fixes.

### PERMIT_DATE

Ideal: populated for Active and Final.

- 1,218 rows already matched Ready-to-Issue `Issued`.
- 113 Final rows with empty Ready-to-Issue tasks but `more_details` … `Issue Date` → FILLED.
- 1 Received shell carried a PERMIT_DATE absent from DATA → cleared when status fixed to In Review.
- Remaining gap: 462 Final (mostly legacy CLOSED conversions) and 1 Active (`Issued` with Ready-to-Issue TBD only) have no recoverable issuance timestamp.

### FINAL_DATE

Ideal: populated for Final.

- Existing values matched Inspection(s) `Finaled` and/or Final* PASS inspections for nearly all populated rows.
- 8 Finaled rows used the **first** Finaled mark (often coinciding with a failed final inspection) while a later Finaled exists → FIXED to latest Finaled.
- 513 Final rows (mostly CLOSED/Closed) missing FINAL_DATE but with Final* PASS inspections → FILLED.
- 74 Final rows remain unfillable (no Finaled task, no qualifying Final* PASS inspection).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 11 | 5 → 5 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 113 | 1 | 781 → 669 |
| FINAL_DATE | 513 | 8 | 1,094 → 581 |

Post-repair coverage by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 218 / 219 (99.5%) | 0 / 219 |
| Final | 1,031 / 1,493 (69.1%) | 1,419 / 1,493 (95.0%) |
| In Review | 0 / 78 | 0 / 78 |
| Inactive | 82 / 205 (40.0%) | 0 / 205 |

Chronology: 0 PERMIT\<FILE, 0 FINAL\<PERMIT, 0 FINAL\<FILE.

Status transitions (flagged): Inactive→Active 7; Inactive→In Review 1; Active→Final 1; Active→In Review 1; In Review→Active 1.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_nevada_county.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_nevada_county_repaired.parquet`
