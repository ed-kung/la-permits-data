# Hurst (TX) data repair

**Summary:** Hurst was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Temple). All 2,000 rows are CivicPlus / EnerGov case payloads (`entity_core` 1,922; `entity_rich` 78). Ninety rows had null STATUS_NORMALIZED for unmapped rental/withdrawn statuses (FILLED); eight more lagged stale `STATUS_ORIGINAL` while `entity.CaseStatus` had advanced (FIXED). FILE_DATE already matched `ApplyDate` on every row. Three Issued rows gained PERMIT_DATE (FILLED); four Complete rows gained FINAL_DATE (FILLED); 89 non-Final rows had spurious FINAL_DATE cleared (FIXED). After repair: Active PERMIT_DATE 99.4%, Final PERMIT_DATE 96.9% / FINAL_DATE 100%.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Hurst, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_hurst.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_hurst_repaired.parquet`

## DATA schema

EnerGov-style nested object with `entity`, `details`, `contacts`, and `processing_status`. Variants differ only by optional review extras:

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_core | 1,922 |
| entity_rich | 78 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` | — |
| FILE_DATE | `entity.ApplyDate` | — |
| PERMIT_DATE | `entity.IssueDate` | — |
| FINAL_DATE | `entity.FinalDate` | `details.FinalizeDate` |

`entity.CaseStatus` and `details.PermitStatus` agree on 1,994/2,000 rows (six Issued rows show PermitStatus=Complete). `processing_status` is null on every sample row (no inspection-date fallback). `CompleteDate` / `ClosedDate` / `OpenedDate` / `RequestDate` / `StartDate` are always null.

## Field assessment

### STATUS_NORMALIZED

Ninety missing values, all from three unmapped `STATUS_ORIGINAL` strings that the upstream normalizer did not handle:

| CaseStatus | n | Filled as | Rationale |
| --- | ---: | --- | --- |
| Rental Resolved | 49 | Final | Closed rental cases; all have `FinalDate` |
| Annual Registration Complete | 38 | Active | In-force annual rental registrations (IssueDate + year-end ExpireDate; FinalDate almost never set) |
| Withdrew | 3 | Inactive | Withdrawn applications |

Eight rows disagreed with current `CaseStatus` because `STATUS_NORMALIZED` was derived from a stale `STATUS_ORIGINAL`:

| CaseStatus | Before STATUS_NORMALIZED | Correct | n | Typical STATUS_ORIGINAL |
| --- | --- | --- | ---: | --- |
| Complete | Active | Final | 5 | issued |
| Issued | In Review | Active | 2 | submitted / fees due |
| Expired | Active | Inactive | 1 | issued |

Canonical `CaseStatus` → STATUS_NORMALIZED map used for repair:

| CaseStatus | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Complete | Final | 1,030 |
| Expired | Inactive | 455 |
| Submitted | In Review | 159 |
| Issued | Active | 132 |
| Void | Inactive | 71 |
| Rental Resolved | Final | 49 |
| In Review | In Review | 40 |
| Annual Registration Complete | Active | 38 |
| Fees Due | In Review | 7 |
| Plan Approval Expired | Inactive | 7 |
| Processed | In Review | 4 |
| Withdrew | Inactive | 3 |
| Denied | Inactive | 3 |
| Submitted - Online | In Review | 2 |

90 FILLED / 8 FIXED. After repair, STATUS matches CaseStatus 1:1 (Final 1,079, Inactive 539, In Review 212, Active 170).

### FILE_DATE

Fully populated (0 missing). Every row matches `entity.ApplyDate` at calendar-day resolution (0 FILLED, 0 FIXED).

### PERMIT_DATE

339 missing before repair; 336 after. When `IssueDate` is present, PERMIT_DATE already matched at calendar-day resolution (1,661 matches; 0 mismatches). Three Issued rows lacked PERMIT_DATE despite a valid `IssueDate` → FILLED (two had stale In Review status; one was already Active).

Remaining Active/Final gaps after repair:

| CaseStatus | STATUS_NORMALIZED | n missing PERMIT_DATE | Notes |
| --- | --- | ---: | --- |
| Issued | Active | 1 | Sign Permit - New with `Issued=False` and null `IssueDate` |
| Complete | Final | 23 | Rental Management Renewal (19) / Legacy Records (4) shells with null `IssueDate` |
| Rental Resolved | Final | 10 | Rental Management cases never issued |

Active coverage after repair is 169/170 (99.4%). Several In Review / Inactive rows retain pre-existing PERMIT_DATE from earlier issuance (Fees Due, Processed, Expired, Void, Withdrew) — left as-is.

### FINAL_DATE

836 missing before repair. Of 1,025 rows already labeled Final, 1,021 had correct FINAL_DATE matching `FinalDate`; the four Complete rows still labeled Active lacked FINAL_DATE despite valid `FinalDate` → FILLED. All 49 Rental Resolved rows already carried FINAL_DATE (kept when status was filled to Final).

Eighty-nine non-Final rows incorrectly carried FINAL_DATE while CaseStatus was Void (57), Expired (14), Submitted (7), Fees Due (3), Withdrew (3), Issued (2), Plan Approval Expired (1), or Annual Registration Complete (2). Repair cleared these (FIXED).

Six Issued rows have `details.FinalizeDate` without `entity.FinalDate`; these are not used for FINAL_DATE because status is Active.

After repair: Final FINAL_DATE coverage is 1,079/1,079 (100%); non-Final FINAL_DATE is empty.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 90 | 8 | 90 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 3 | 0 | 339 → 336 |
| FINAL_DATE | 4 | 89 | 836 → 921 |

Coverage after repair by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 169 / 170 (99.4%) | 0 / 170 |
| Final | 1,046 / 1,079 (96.9%) | 1,079 / 1,079 (100%) |
| In Review | 9 / 212 (4.2%) | 0 / 212 |
| Inactive | 440 / 539 (81.6%) | 0 / 539 |

FILE_DATE: 2,000 / 2,000 (100%).
