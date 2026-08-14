# Leesburg (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Leesburg**. DATA is a sparse `mini_set` portal shell in two key-set variants (`application_status` vs `job_status`) with **no date fields**. Upstream correctly normalized all 1,342 application-schema rows but left all 658 job-schema rows with null `STATUS_NORMALIZED` / `STATUS_ORIGINAL`. Repair filled those 658 from `job_status` (0 FIXED). `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` were already missing on every row and remain unrecoverable from DATA. After repair: STATUS fully populated; date coverage 0% across all statuses.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Leesburg was the first pair without `agent/scripts/fl/data_repair_fl_leesburg.py`.

## DATA shape

| Schema prefix | n | Keys |
| --- | ---: | --- |
| `mini_set_application_*` | 1,342 | `application_status`, `application_type`, `parcel`, `contractor`, `address`, `mini_set` |
| `mini_set_job_*` | 658 | `job_status`, `job_type`, `job_description`, `address`, `mini_set` |

`INFERRED_SCHEMA` appends a status slug (e.g. `mini_set_application_closed`, `mini_set_job_certificate_issued`). Dominant: `mini_set_application_closed` (1,177).

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `application_status` or `job_status` |
| FILE_DATE | *(none — no application/submittal date)* |
| PERMIT_DATE | *(none — no issue/printed date)* |
| FINAL_DATE | *(none — no finaled/CO/completion date)* |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,272; null 658; Inactive 63; Active 6; In Review 1.

Application-schema mapping (already correct; 0 changes):

| application_status | n | STATUS_NORMALIZED |
| --- | ---: | --- |
| Closed | 1,177 | Final |
| Certificate Issued | 69 | Final |
| Certificate of Completion | 26 | Final |
| Withdrawn | 40 | Inactive |
| Abandoned | 23 | Inactive |
| Permit Printed | 6 | Active |
| On Hold | 1 | In Review |

Job-schema rows were **incorrectly missing** status because upstream only read `application_status`. Filled from `job_status`:

| job_status | n | → STATUS_NORMALIZED |
| --- | ---: | --- |
| Certificate Issued | 365 | Final |
| Closed | 230 | Final |
| Withdrawn | 31 | Inactive |
| Certificate of Completion | 14 | Final |
| Permit Printed | 11 | Active |
| Abandoned | 6 | Inactive |
| Approved | 1 | In Review |

Flags: **658 FILLED, 0 FIXED**. After: Final 1,881; Inactive 100; Active 17; In Review 2; **0 null**.

### FILE_DATE

Missing on 2,000/2,000 before and after. No application, created, or submittal timestamp exists in either mini_set variant. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing on 2,000/2,000 before and after, including all Active (17) and Final (1,881) rows. No issue / printed date key exists. Flags: **0 FILLED, 0 FIXED**.

### FINAL_DATE

Missing on 2,000/2,000 before and after, including all Final rows. No finaled, CO, or completion date key exists. Flags: **0 FILLED, 0 FIXED**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 658 | 0 | 658 → 0 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Ideal coverage after repair: FILE_DATE 0%; Active/Final PERMIT_DATE 0/1,898; Final FINAL_DATE 0/1,881.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_leesburg.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_leesburg_repaired.parquet`
