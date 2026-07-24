# La Habra CA data repair

**Summary:** La Habra’s 2,000 sample records are Tyler EnerGov-style payloads (`entity` / `details` / `fees`, optionally with `reviews`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct against `CaseStatus` / `ApplyDate`. `PERMIT_DATE` already mirrors `IssueDate` wherever both exist (Active 100%; Final 94.3%). Material repairs: clear 12 spurious `FINAL_DATE` values on In Review (`Fees Due`) rows, and fill 1 missing Final `FINAL_DATE` from `entity.FinalDate`. Remaining Final gaps (85 `PERMIT_DATE`, 83 `FINAL_DATE`) lack issuance/final dates in DATA (mostly legacy `Complete`). Script: `agent/scripts/data_repair_ca_la_habra.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "La Habra"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | La Habra, CA (after La Cañada Flintridge) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,875 |
| `entity_fees_reviews` | 125 |

Both schemas share `entity`, `details`, `contacts`, `fees`, `processing_status`. The richer variant adds `reviews` / `holds` / `attachments` / `more_info`. Status and dates come from `entity` (with `details.PermitStatus` / `IssueDate` / `FinalizeDate` as mirrors; timezone offsets can shift the UTC calendar day vs `entity`, so `entity` is preferred).

Canonical EnerGov fields:

| DATA field | Target column |
| --- | --- |
| `entity.CaseStatus` | `STATUS_NORMALIZED` |
| `entity.ApplyDate` | `FILE_DATE` |
| `entity.IssueDate` | `PERMIT_DATE` |
| `entity.FinalDate` (fallback `details.FinalizeDate`) | `FINAL_DATE` |

`STATUS_ORIGINAL` matches `entity.CaseStatus` 1:1 (case-insensitive).

## Field assessment

### STATUS_NORMALIZED — correct (0 FILLED / 0 FIXED)

| CaseStatus | STATUS_NORMALIZED | n |
| --- | --- | --- |
| Finaled | Final | 1,395 |
| Complete | Final | 86 |
| Issued | Active | 181 |
| Expired | Inactive | 180 |
| Void | Inactive | 3 |
| Cancelled | Inactive | 3 |
| Fees Due | In Review | 49 |
| In Review | In Review | 49 |
| Submitted - Online | In Review | 28 |
| Ready to Issue | In Review | 9 |
| Review Completed | In Review | 8 |
| Fees Paid | In Review | 5 |
| Submitted | In Review | 2 |
| Plan Check Approved | In Review | 1 |
| Stop Work Order | In Review | 1 |

No missing or mis-mapped statuses. Repair re-derives from `CaseStatus` for robustness but changes nothing on the sample. `Stop Work Order` is kept as In Review (same convention as Hawthorne).

### FILE_DATE — correct (0 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- All 2,000 rows populated; every value equals the UTC calendar date of `entity.ApplyDate`.
- `OpenedDate` / `RequestDate` / `StartDate` / `CompleteDate` / `ClosedDate` are null throughout this sample.

### PERMIT_DATE — correct where `IssueDate` exists; 85 Final unfillable (0 FILLED / 0 FIXED)

- Ideal: populated for Active and Final.
- When present, `PERMIT_DATE` always matches `entity.IssueDate` (1,777 / 1,777). The 223 missing values are exactly the 223 null-`IssueDate` rows.
- By status after repair:
  - Active: 181 / 181 (100%)
  - Final: 1,396 / 1,481 (94.3%) — gaps are 83 `Complete` + 2 `Finaled` with `Issued=False` and null `IssueDate`
  - In Review: 20 / 152 have an `IssueDate`-backed date (mostly `Fees Due` after prior issuance); CaseStatus remains authoritative, so status is not remapped to Active
  - Inactive: 180 / 186 (`Expired` all have issuance; `Void`/`Cancelled` do not)
- `FILE_DATE` is not used as an issuance proxy (same convention as other EnerGov cities).

### FINAL_DATE — 12 incorrect non-Final stamps + 1 fillable Final gap

- Ideal: populated for Final; absent otherwise.
- Before repair: Final 1,397 / 1,481 had `FINAL_DATE` matching `entity.FinalDate`; 12 In Review (`Fees Due`) rows also carried `FINAL_DATE` copied from `entity.FinalDate` while CaseStatus was still open for fee collection.
- Repairs:
  - **FIXED × 12:** clear spurious `FINAL_DATE` on `Fees Due` rows (CaseStatus authoritative; stamp is not treated as a sign-off).
  - **FILLED × 1:** Finaled case `16-0916` had null `FINAL_DATE` but plausible `entity.FinalDate` / `details.FinalizeDate` of 2028-12-06 (within the 1980–2035 year gate).
- After repair: Final 1,398 / 1,481 (94.4%); Active / In Review / Inactive all 0%.
- Remaining 83 Final gaps are `CaseStatus=Complete` rows with null `FinalDate` / `FinalizeDate` / `CompleteDate` / `ClosedDate` in DATA (typically also missing `IssueDate`). Not fillable.

## Repair function

`agent/scripts/data_repair_ca_la_habra.py` → `data_repair(df)`

- Overwrites incorrect / missing fields from DATA
- Adds `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`} and `INFERRED_SCHEMA`
- Rejects implausible date years (outside 1980–2035) before using them as fill/fix sources
- Clears `FINAL_DATE` on non-Final rows
- CLI preview on the LA sample:

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 0 | 0 | 0 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 223 → 223 |
| `FINAL_DATE` | 1 | 12 | 591 → 602 |

Missing `FINAL_DATE` rises by 11 because 12 incorrect values are cleared and only 1 true Final gap is filled.

## Artifacts

- Repair script: `agent/scripts/data_repair_ca_la_habra.py`
- No derived datasets written under `AGENT_DATA_PATH`
