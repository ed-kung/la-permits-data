# Alhambra CA data repair

**Summary:** Alhambra’s 2,000 sample records use a Tyler EnerGov-style `entity` / `details` DATA payload (three key-set variants). `STATUS_NORMALIZED` was missing for 87 records whose `CaseStatus` values were never mapped upstream; all are now fillable (`In Review` × 86, `Inactive` × 1). `FILE_DATE` is complete and matches `entity.ApplyDate`. `PERMIT_DATE` and `FINAL_DATE` already mirror `IssueDate` / `FinalDate` when present; 17 Active/Final rows still lack `PERMIT_DATE` because `IssueDate` is null in DATA (not safely proxyable). Repair script: `agent/scripts/data_repair_ca_alhambra.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Alhambra"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Alhambra, CA |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,612 |
| `entity_fees_reviews` | 294 |
| `entity_basic` | 94 |

All schemas share `entity`, `details`, `contacts`, `processing_status`. Variants differ by optional `fees` and by `reviews` / `holds` / `attachments` / `more_info`.

Canonical date/status fields are under `entity` (with `details.PermitStatus` / `details.FinalizeDate` as identical or fallback mirrors). `STATUS_ORIGINAL` matches `entity.CaseStatus` 1:1 (case-insensitive).

## Field assessment

### STATUS_NORMALIZED — 87 missing, all fillable (87 FILLED / 0 FIXED)

Existing non-null mappings are consistent with `CaseStatus` and need no correction:

| CaseStatus | STATUS_NORMALIZED | n |
| --- | --- | --- |
| Permit Issued | Active | 483 |
| Complete | Final | 192 |
| Permit Finaled | Final | 272 |
| Expired | Inactive | 316 |
| Plan Approval Expired | Inactive | 154 |
| Void | Inactive | 25 |
| In Review / Fees Due / Fees Paid / On Hold / Submitted / Submitted - Online | In Review | 471 |

Upstream left these unmapped (`STATUS_NORMALIZED` null):

| CaseStatus | Repair → | n |
| --- | --- | --- |
| Planning Division Initial Review | In Review | 46 |
| Additional Documents Required | In Review | 36 |
| Public Works Processing | In Review | 4 |
| Not Applicable | Inactive | 1 |

After repair: 0 missing statuses. Distribution: In Review 557, Inactive 496, Active 483, Final 464.

### FILE_DATE — correct (0 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- All 2,000 rows populated; every value equals the UTC calendar date of `entity.ApplyDate`.
- `OpenedDate` / `RequestDate` / `CompleteDate` / `ClosedDate` are universally null in this sample.
- Repair re-derives from `ApplyDate` for robustness but changes nothing on the sample.

### PERMIT_DATE — correct where `IssueDate` exists; 17 Active/Final unfillable (0 FILLED / 0 FIXED)

- Ideal: populated for Active and Final.
- When present, `PERMIT_DATE` always matches `entity.IssueDate` (1,348 / 1,348).
- Active: 478 / 483 (99.0%) have `PERMIT_DATE`; Final: 452 / 464 (97.4%).
- The 17 gaps (5 Active “Permit Issued”, 12 Final “Complete”/“Permit Finaled”) have null `IssueDate` and `details.Issued == False` in DATA. Same-day `ApplyDate` ≈ `IssueDate` rates for those CaseTypes are low (~0–19%), so `FILE_DATE` is not used as a proxy.
- Remaining missing dates are mostly In Review / pre-issuance Inactive rows, where absence is expected.

### FINAL_DATE — correct for Final (0 FILLED / 0 FIXED)

- Ideal: populated for Final.
- All 464 Final rows have `FINAL_DATE`, matching `entity.FinalDate` (and usually `details.FinalizeDate`; 1 record differs by one calendar day due to timezone encoding — upstream/`FinalDate` kept).
- No Final row is missing a recoverable final date; `CompleteDate` / `ClosedDate` are always null.
- Some non-Final rows also carry `FinalDate` (e.g. Inactive 81, Active 6); left as-is.

## Repair function

`agent/scripts/data_repair_ca_alhambra.py` → `data_repair(df)`

- Overwrites incorrect / missing fields from DATA
- Adds `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`} and `INFERRED_SCHEMA`
- CLI preview on the LA sample:

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 87 | 0 | 87 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 652 → 652 |
| FINAL_DATE | 0 | 0 | 1,448 → 1,448 |

## Artifacts

- `agent/scripts/data_repair_ca_alhambra.py`
- `agent/reports/2026-07-23-alhambra-data-repair.md`
