# Williamson County (TX) data repair

**Summary:** Williamson County was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. Its DATA column is a flat MyGovernmentOnline (MGO) project payload (same family as Kendall / Hays County). Of 2,000 sample rows, FILE_DATE is already correct against `DateCreated`. STATUS_NORMALIZED had 167 nulls for four portal statuses the upstream normalizer did not cover — all filled from `ProjectStatus`. PERMIT_DATE and FINAL_DATE remain universally missing: `DateIssued` and `DateUpdated` are the .NET sentinel `0001-01-01` on every row, and no other issuance or finaling timestamp exists.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in sample order. Existing TX scripts covered through Kendall County / Leon Valley / etc.; **Williamson County, TX** was the first missing (`agent/scripts/tx/data_repair_tx_williamson_county.py`).

## DATA schema

Nearly every record shares the same top-level MGO keys. Recorded in `INFERRED_SCHEMA`:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| mgo_ppm | 1,996 | Flat MGO project payload with `PaymentProcessorModule` = `MGO` |
| mgo_base | 4 | Same keys without `PaymentProcessorModule` |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` (whitespace-stripped) | — |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (when not sentinel) | — (always sentinel in sample) |
| FINAL_DATE | — (none available) | — |

`ProjectStatus` values observed (trailing spaces stripped): Approved (1,349), Pending (312), Pending Precon (108), Under Review (81), Application Paid/Review Pending (61), Authorization to Construct (34), Design Review Complete (23), Closed (10), Waiting for Applicant (8), Disapproved (7), Accepted (5), Variance Review (2).

## Findings by field

### STATUS_NORMALIZED

Before: Active 1,349, In Review 467, Final 10, Inactive 7, **missing 167**.

Already-populated rows match `ProjectStatus` 1:1 (0 mismatches):

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Approved | approved | Active | 1,349 |
| Pending | pending | In Review | 312 |
| Under Review | under review | In Review | 81 |
| Application Paid/Review Pending | application paid/review pending | In Review | 61 |
| Waiting for Applicant | waiting for applicant | In Review | 8 |
| Accepted | accepted | In Review | 5 |
| Closed | closed | Final | 10 |
| Disapproved | disapproved | Inactive | 7 |

Missing statuses were unmapped portal labels; all fillable:

| ProjectStatus | Filled as | n | Rationale |
| --- | --- | ---: | --- |
| Pending Precon | In Review | 108 | Pre-construction pending stage |
| Authorization to Construct | Active | 34 | Construction authorized (issued/approved analogue) |
| Design Review Complete | In Review | 23 | Intermediate review milestone, not yet authorized |
| Variance Review | In Review | 2 | Review workflow |

Ideal: populated for all records — **achieved (100%)**. **FILLED 167, FIXED 0.**

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution. Ideal: populated for all records — **achieved (100%)**. **FILLED 0, FIXED 0.**

### PERMIT_DATE

Universally missing (2,000 / 2,000) before and after. `DateIssued` is `0001-01-01T00:00:00` on every row. Balance / placard / receipt / power-request date fields are empty or null and are not safe issuance proxies. `ProjectStatusIsPrintPermit` is False even for Approved / Authorization to Construct rows, so it cannot proxy issuance.

Ideal: populated for Active and Final — **not achievable from DATA** (0/1,383 Active, 0/10 Final after status repair).

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also the .NET sentinel; no completion / CO / signoff timestamp exists in the flat MGO payload.

Ideal: populated for Final — **not achievable from DATA** (0/10).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 167 | 0 | 167 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Post-repair STATUS_NORMALIZED: Active 1,383, In Review 600, Final 10, Inactive 7.

Post-repair coverage:

- Active: FILE 100%, PERMIT 0%, FINAL 0%
- Final: FILE 100%, PERMIT 0%, FINAL 0%
- In Review: FILE 100%, PERMIT 0%, FINAL 0%
- Inactive: FILE 100%, PERMIT 0%, FINAL 0%

Date-order violations: none (no PERMIT/FINAL dates to compare).

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_williamson_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_williamson_county_repaired.parquet`
