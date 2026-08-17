# Waco (TX) data repair

**Summary:** Waco was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Rosenberg). All 1,999 rows are CivicPlus / EnerGov case payloads (`entity_core` 1,803; `entity_rich` 196). STATUS_NORMALIZED lagged stale `STATUS_ORIGINAL` on 28 rows while `entity.CaseStatus` had already advanced — all FIXED. FILE_DATE already matched `ApplyDate` on every row. Ten Issued rows gained PERMIT_DATE (FILLED); 16 Finaled rows gained FINAL_DATE (FILLED); 293 non-Final rows had spurious FINAL_DATE cleared (FIXED). After repair: Active PERMIT_DATE 100%, Final PERMIT_DATE 99.8% / FINAL_DATE 100%.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Waco, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_waco.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_waco_repaired.parquet`

## DATA schema

EnerGov-style nested object with `entity`, `details`, `contacts`, and `processing_status`. Variants differ only by optional review extras:

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_core | 1,803 |
| entity_rich | 196 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` | — |
| FILE_DATE | `entity.ApplyDate` | — |
| PERMIT_DATE | `entity.IssueDate` | — |
| FINAL_DATE | `entity.FinalDate` | `details.FinalizeDate` |

`entity.CaseStatus` and `details.PermitStatus` agree on 1,997/1,999 rows. `processing_status` is null on every sample row (no inspection-date fallback). `CompleteDate` / `ClosedDate` / `OpenedDate` / `RequestDate` are unused (always null or unused for repair).

## Field assessment

### STATUS_NORMALIZED

No missing values. Twenty-eight rows disagreed with current `CaseStatus` because `STATUS_NORMALIZED` was derived from a stale `STATUS_ORIGINAL`:

| CaseStatus | Before STATUS_NORMALIZED | Correct | n | Typical STATUS_ORIGINAL |
| --- | --- | --- | ---: | --- |
| Finaled | Active | Final | 16 | issued |
| Issued | In Review | Active | 10 | in review / payment pending / requested |
| Expired | Active | Inactive | 2 | issued |

Canonical `CaseStatus` → STATUS_NORMALIZED map used for repair:

| CaseStatus | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Finaled | Final | 910 |
| Issued | Active | 369 |
| Requested | In Review | 293 |
| Withdrawn | Inactive | 225 |
| Expired | Inactive | 63 |
| Payment Pending | In Review | 51 |
| In Review | In Review | 25 |
| On Hold | In Review | 22 |
| Canceled | Inactive | 21 |
| Waiting on Response | In Review | 10 |
| Void | Inactive | 7 |
| Paid In Full | In Review | 2 |
| Review Only | In Review | 1 |

0 FILLED / 28 FIXED. After repair, STATUS matches CaseStatus 1:1 (Final 910, In Review 404, Active 369, Inactive 316).

### FILE_DATE

Fully populated (0 missing). Every row matches `entity.ApplyDate` at calendar-day resolution (0 FILLED, 0 FIXED).

### PERMIT_DATE

658 missing before repair; 648 after. When `IssueDate` is present, PERMIT_DATE already matched at calendar-day resolution (1,341 matches; 0 mismatches). Ten Issued rows with stale In Review status lacked PERMIT_DATE despite a valid `IssueDate` → FILLED.

Remaining Active/Final gaps after repair:

| CaseStatus | STATUS_NORMALIZED | n missing PERMIT_DATE | Notes |
| --- | --- | ---: | --- |
| Finaled | Final | 2 | Right-of-Way / Gas shells with null `IssueDate` and `Issued=False` |

Active coverage after repair is 369/369 (100%). One On Hold (In Review) row retains a pre-existing PERMIT_DATE from an earlier issuance — left as-is.

### FINAL_DATE

812 missing before repair. All 894 rows already labeled Final had correct FINAL_DATE matching `FinalDate`. Sixteen Finaled rows still labeled Active had `FinalDate`/`FinalizeDate` but null FINAL_DATE → FILLED.

Two hundred ninety-three non-Final rows incorrectly carried FINAL_DATE copied from `FinalDate` while CaseStatus was Withdrawn (204), Expired (60), Canceled (19), Void (6), Issued (3), or Review Only (1). Repair cleared these (FIXED).

After repair: Final FINAL_DATE coverage is 910/910 (100%); non-Final FINAL_DATE is empty.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 28 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 10 | 0 | 658 → 648 |
| FINAL_DATE | 16 | 293 | 812 → 1,089 |

Coverage after repair by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 369 / 369 (100%) | 0 / 369 |
| Final | 908 / 910 (99.8%) | 910 / 910 (100%) |
| In Review | 1 / 404 (0.2%) | 0 / 404 |
| Inactive | 73 / 316 (23.1%) | 0 / 316 |

FILE_DATE: 1,999 / 1,999 (100%).
