# Arcadia CA data repair

**Summary:** Arcadia’s 2,000 sample records use a Tyler EnerGov-style `entity` / `details` DATA payload (two key-set variants). The only systematic field error is `STATUS_NORMALIZED`: 25 `CaseStatus=Estimate` rows were incorrectly labeled `Final` (pre-issuance quotes with no `IssueDate`/`FinalDate`); all are now `FIXED` → `In Review`. `FILE_DATE` is complete and matches `entity.ApplyDate`. `PERMIT_DATE` / `FINAL_DATE` already mirror `IssueDate` / `FinalDate` when present and plausible. Remaining gaps: 13 Active (`Approved`) and 8 Final (legacy `Complete`) lack `IssueDate`; 3 Final rows have corrupt `FinalDate` years (2205–5201) and are correctly left null. Repair script: `agent/scripts/data_repair_ca_arcadia.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Arcadia"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Arcadia, CA (after Alhambra) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,977 |
| `entity_fees_reviews` | 23 |

All schemas share `entity`, `details`, `contacts`, `processing_status`, `fees`. The reviews variant also has empty/null `reviews` / `holds` / `attachments` / `more_info` blocks; status and dates still come from `entity`.

Canonical date/status fields are under `entity` (with `details.PermitStatus` / `details.FinalizeDate` as identical or fallback mirrors). `STATUS_ORIGINAL` matches `entity.CaseStatus` 1:1 (case-insensitive).

## Field assessment

### STATUS_NORMALIZED — 25 incorrect (0 FILLED / 25 FIXED)

Existing non-null mappings that need no correction:

| CaseStatus | STATUS_NORMALIZED | n |
| --- | --- | --- |
| Complete | Final | 1,648 |
| Issued | Active | 124 |
| Approved | Active | 13 |
| Expired | Inactive | 169 |
| Void | Inactive | 19 |
| Withdrawn | Inactive | 2 |

Incorrect upstream mapping repaired:

| CaseStatus | Before | Repair → | n |
| --- | --- | --- | --- |
| Estimate | Final | In Review | 25 |

Evidence that Estimate ≠ Final: all 25 have `details.Issued == False`, null `IssueDate`, null `FinalDate`, and are mostly water-service / utility estimate CaseTypes. No records had missing `STATUS_NORMALIZED`.

After repair: Final 1,648, Inactive 190, Active 137, In Review 25.

### FILE_DATE — correct (0 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- All 2,000 rows populated; every value equals the UTC calendar date of `entity.ApplyDate`.
- `OpenedDate` / `RequestDate` / `StartDate` / `CompleteDate` / `ClosedDate` are universally null in this sample.
- Repair re-derives from `ApplyDate` for robustness but changes nothing on the sample.

### PERMIT_DATE — correct where `IssueDate` exists; 21 Active/Final unfillable (0 FILLED / 0 FIXED)

- Ideal: populated for Active and Final.
- When present, `PERMIT_DATE` always matches `entity.IssueDate` (1,934 / 1,934). The 66 missing `PERMIT_DATE` values are exactly the 66 null `IssueDate` rows.
- After status repair:
  - Active: 124 / 137 (90.5%) have `PERMIT_DATE` — the 13 gaps are all `Approved` with `Issued=False`.
  - Final: 1,640 / 1,648 (99.5%) — the 8 gaps are legacy CaseTypes (Solar/Fire/MEP/Electrical/Roof Legacy) with null `IssueDate` and `Issued=False`.
- `ApplyDate ≈ IssueDate` same-day rate is ~80%, but (as with Alhambra) `FILE_DATE` is not used as a proxy.
- In Review / pre-issuance Inactive gaps are expected.

### FINAL_DATE — correct for Final except 3 corrupt DATA values (0 FILLED / 0 FIXED)

- Ideal: populated for Final.
- After moving Estimates out of Final: 1,645 / 1,648 Final rows (99.8%) have `FINAL_DATE`, matching plausible `entity.FinalDate`.
- The 3 remaining Final gaps have `FinalDate` / `details.FinalizeDate` in years **2205**, **5200**, and **5201** (Plumbing/Roof/Mechanical Legacy). Upstream left `FINAL_DATE` null; the repair’s year gate (1980–2035) rejects these sentinels so they are not filled.
- Some non-Final rows also carry `FinalDate` (e.g. Issued 49, Expired 18, Withdrawn 2); left as-is.

## Repair function

`agent/scripts/data_repair_ca_arcadia.py` → `data_repair(df)`

- Overwrites incorrect / missing fields from DATA
- Adds `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`} and `INFERRED_SCHEMA`
- Rejects implausible date years before using them as fill/fix sources
- CLI preview on the LA sample:

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 25 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 66 → 66 |
| FINAL_DATE | 0 | 0 | 286 → 286 |

(`FINAL_DATE` missing count is unchanged because the 25 Estimate rows still lack a final date after becoming In Review, and the 3 corrupt Final dates remain null.)

## Artifacts

- Script: `agent/scripts/data_repair_ca_arcadia.py`
- No derived parquet written (assessment + repair function only)
