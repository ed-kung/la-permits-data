# Lake Forest (CA) data repair — 2026-07-28

**Summary:** Lake Forest was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed 2,000 Tyler EnerGov records against `DATA`. Main defects: 9 unmapped `Active - Expired` statuses (left null); 355 In Review shells (`Received Online` / `Initiated`) that already carry `Issued=True` and a real `IssueDate`; 4 Active shells with `FinalDate`/`FinalizeDate` (status lag); and 100 spurious `FINAL_DATE` stamps on Inactive/Active rows from case-closure `FinalDate`. Repair fills/fixes status (9 FILLED · 359 FIXED), clears those 100 finals, and leaves `FILE_DATE` / `PERMIT_DATE` unchanged (already matched `ApplyDate` / `IssueDate`). Script: `agent/scripts/ca/data_repair_ca_lake_forest.py`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample appearance order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Lake Forest, CA**.

## DATA schema

All rows share Tyler EnerGov top-level keys. Canonical dates/status live under `entity` with `details` fallbacks (`CaseStatus` / `PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` / `FinalizeDate`). `processing_status` is always null in this sample. Content variants in `INFERRED_SCHEMA`:

| Schema | n | Top-level keys |
| --- | ---: | --- |
| `entity_fees` | 1,955 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 45 | above + reviews, holds, attachments, more_info |

## Field assessment

### STATUS_NORMALIZED

| CaseStatus | Before STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Closed - Finaled | Final | 1,076 |
| Received Online | In Review | 455 |
| Active | Active | 213 |
| Closed - Expired | Inactive | 128 |
| Initiated | In Review | 79 |
| Void | Inactive | 28 |
| Ready to Issue | In Review | 10 |
| Active - Expired | *(missing)* | 9 |
| Closed - Withdrawn | Inactive | 2 |

- Upstream never mapped `Active - Expired` (issued permits past ExpireDate) → 9 null statuses.
- 355 `Received Online` / `Initiated` rows have `details.Issued=True` and a non-sentinel `IssueDate` (347 same-day OTC; 8 later IssueDate) while STATUS stayed In Review — issuance evidence contradicts CaseStatus.
- 4 `Active` rows already have `FinalDate` / `FinalizeDate` but CaseStatus was never moved to Closed - Finaled.

### FILE_DATE

- 0 missing; all 2,000 match `entity.ApplyDate` at day resolution. No repair needed.

### PERMIT_DATE

- 211 missing. When present, every value matches `IssueDate` (0 incorrect).
- 4 rows have `IssueDate=2999-01-01` (sentinel) → correctly left missing by the 1990–2035 window (1 Active grading shell with `Issued=False`; 3 Void/Expired).
- After status upgrades, Active PERMIT coverage is 563/564 (99.8%) and Final 1,075/1,080 (99.5%). Remaining In Review rows (189) correctly lack PERMIT_DATE.

### FINAL_DATE

- Among Final: 21 missing — all `Closed - Finaled` with null `FinalDate` / `FinalizeDate` and empty `processing_status` (mostly 2010–2012 encroachment shells). Not fillable from DATA.
- **Spurious FINAL_DATE (100):** Inactive Closed - Expired (75), Void (24), and one Active - Expired carried `entity.FinalDate` as a case-closure stamp; 4 Active rows had real completion stamps and were upgraded to Final (dates retained) rather than cleared.
- ExpireDate is a validity window, not used as completion.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 9 | 359 | 9 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 211 → 211 |
| FINAL_DATE | 0 | 100 | 841 → 941 |

Status transitions: `(null)` → Inactive 9 (Active - Expired); In Review → Active 355; Active → Final 4.

Status after repair: Final 1,080 · Active 564 · In Review 189 · Inactive 167.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 564 | 100% | 99.8% | 0% |
| Final | 1,080 | 100% | 99.5% | 98.1% |
| In Review | 189 | 100% | 0% | 0% |
| Inactive | 167 | 100% | 90.4% | 0% |

Chronology inversions after repair (3 `PERMIT < FILE`, 2 `FINAL < PERMIT`) mirror inverted Apply/Issue/Final timestamps already present in `entity`.

## Notes / limitations

- `Active - Expired` is treated as Inactive and is sticky even when `FinalDate` is present (1 row).
- Sentinel `IssueDate` / `ExpireDate` year 2999 is rejected; no alternate issuance field exists for those shells.
- 21 Final rows without `FinalDate` remain missing FINAL_DATE.
- Clearing non-Final case-closure stamps intentionally increases FINAL_DATE missingness (841 → 941).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_lake_forest.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_lake_forest_repaired.parquet`
