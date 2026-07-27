# Palm Springs (CA) data repair

**Summary:** Palm Springs was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Tyler EnerGov `DATA` JSON. Status is now fully populated (**FILLED 6**): five `Corrections Requested` and one `Outstanding COA's` null-status rows were mapped to In Review. `FILE_DATE` and `PERMIT_DATE` already matched `entity.ApplyDate` / `entity.IssueDate` for every row where those source dates exist (no changes). `FINAL_DATE` had **70 FIXED** clears of spurious finals on Void / Denied / Expired / On Hold / Submitted - Online rows (case-closure stamps, not sign-offs). Remaining Final gaps (**390 / 867**) are Complete rows with null `FinalDate` / `FinalizeDate`, mostly ApplyDate 2001–2013 migrations.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Palm Springs, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_palm_springs.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Tyler EnerGov portal payloads with top-level keys `entity`, `details`, `contacts`, `fees`, `processing_status`. Optional review/hold blocks define a second schema:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,955 | Core entity + details + fees (+ contacts, processing_status) |
| `entity_fees_reviews` | 45 | Above plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (same as `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` (fallback: `details.ApplyDate`) |
| `PERMIT_DATE` | `entity.IssueDate` (fallback: `details.IssueDate`) |
| `FINAL_DATE` | `entity.FinalDate` (fallback: `details.FinalizeDate`) |

## Field assessment

### STATUS_NORMALIZED

Upstream mapping was already correct for all known CaseStatus values in the sample:

| CaseStatus | Prior STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Issued | Active | 889 |
| Complete | Final | 867 |
| Expired / Void / Denied / Canceled | Inactive | 177 |
| In Review / Fees Due / Fees Paid / On Hold / Ready to Review / Submitted / Submitted - Online | In Review | 61 |
| Corrections Requested | **null** | 5 |
| Outstanding COA's | **null** | 1 |

Repair: map the six unmapped CaseStatus labels to **In Review** (pre-issuance; all have null `IssueDate`).

### FILE_DATE

All 2,000 rows have `FILE_DATE`, and every value matches the UTC calendar day of `entity.ApplyDate`. No fills or fixes.

### PERMIT_DATE

Whenever `IssueDate` is present (1,862 rows), `PERMIT_DATE` matches exactly. Missingness (138) coincides with null `IssueDate` / `Issued=False`, almost entirely In Review and Inactive. Ideal coverage after repair:

- Active: 889 / 889 (100%)
- Final: 866 / 867 (99.9%) — one Revision (`REV-2023-0134`, Complete, Issued=False) has no issuance date in DATA

No fills or fixes possible from DATA.

### FINAL_DATE

For Complete (Final) rows, `FINAL_DATE` already matches `FinalDate` / `FinalizeDate` when those exist (477 / 867). The other 390 Complete rows have no final date anywhere in DATA (Apply years 2001–2013).

**Incorrect values:** 70 non-Final rows carried `FINAL_DATE` copied from `entity.FinalDate` (Void 52, Denied 15, Expired 1, On Hold 1, Submitted - Online 1). In EnerGov those stamps mark case closure, not permit final/sign-off, so they were cleared (**FIXED**).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 6 | 0 | 6 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 138 → 138 |
| FINAL_DATE | 0 | 70 | 1,453 → 1,523 |

Missing `FINAL_DATE` rises because 70 spurious non-Final finals were removed; Final-status coverage is unchanged at 477 / 867 (55.0%).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_palm_springs.py`
- Repaired sample parquet: `AGENT_DATA_PATH/permits_ca_palm_springs_repaired.parquet`
