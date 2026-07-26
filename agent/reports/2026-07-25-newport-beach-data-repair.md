# Newport Beach (CA) data repair

**Summary:** Among CA sample jurisdictions, Newport Beach was the first `(JURISDICTION, STATE)` pair without a repair script. Its DATA JSON is a civic-portal payload with `entity` / `details` cores and three key-set variants. `FILE_DATE` already matched `entity.ApplyDate` for all 2,000 rows. Fourteen status errors/gaps came from stale `STATUS_ORIGINAL` vs current `CaseStatus` (2 FILLED, 12 FIXED). Two Active `PERMIT_DATE` gaps were filled from `IssueDate` and one spurious In Review `PERMIT_DATE` was cleared. Twelve Final `FINAL_DATE` gaps were filled (FinalDate or Approved `*Final*` inspections); 140 non-Final `FINAL_DATE` values were cleared. Remaining Final `PERMIT_DATE` gaps (~240) are mostly Closed Residential Building Reports and Encroachment shells with blank `IssueDate`.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Newport Beach, CA** (2,000 rows) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/ca/data_repair_ca_newport_beach.py`
- Artifact: `AGENT_DATA_PATH/newport_beach_repaired_sample.parquet`

## DATA schema

Every record has `entity`, `details`, `contacts`, and `processing_status`. Canonical fields:

| DATA field | Target column |
| --- | --- |
| `entity.CaseStatus` (fallback `details.PermitStatus`) | `STATUS_NORMALIZED` |
| `entity.ApplyDate` (fallback `details.ApplyDate`) | `FILE_DATE` |
| `entity.IssueDate` (fallback `details.IssueDate`) | `PERMIT_DATE` |
| `entity.FinalDate` / `details.FinalizeDate` (fallback Approved `*Final*` inspection) | `FINAL_DATE` |

`INFERRED_SCHEMA` variants (same repair logic):

- `portal_fees` — 1,299 rows (`+ fees`)
- `portal_basic` — 624 rows (core keys only)
- `portal_full` — 77 rows (`+ fees`, `holds`, `reviews`, `more_info`, `attachments`)

Status map from `CaseStatus`: Final/Closed → Final; Approved/Issued/Reissued → Active; Applied/Pending/Plan Check */In Review → In Review; Declined/Expired/Cancelled/Void → Inactive.

## Field assessment

### STATUS_NORMALIZED

- **Missing:** 2 / 2,000 (`plan check applied` originals left unmapped)
- **Correctness:** Mostly aligned with `CaseStatus`, but 14 rows used stale `STATUS_ORIGINAL` instead of current `CaseStatus` (CaseStatus and PermitStatus agree on 1,999/2,000 rows):
  - 7× `Final` with `STATUS_ORIGINAL=issued` → labeled **Active**
  - 2× `Issued` with `STATUS_ORIGINAL=final` → labeled **Final**
  - 1× `Issued` with `STATUS_ORIGINAL=applied` → labeled **In Review**
  - 1× `Expired` with `STATUS_ORIGINAL=issued` → labeled **Active**
  - 1× `In Review` with `STATUS_ORIGINAL=issued` → labeled **Active**
  - 2× missing (`Plan Check Applied` / `Issued` with stale originals)
- **Repair:** **2 FILLED**, **12 FIXED** · missing after: 0
- After: Final 1,097 · Active 669 · Inactive 179 · In Review 55

### FILE_DATE

- **Missing:** 0 / 2,000
- **Correctness:** Calendar-day match to `entity.ApplyDate` for all rows (prefer entity over details; 9 rows differ only by UTC vs local timestamp crossing midnight)
- **Repair:** 0 FILLED, 0 FIXED (already complete)

### PERMIT_DATE

- **Missing before:** 395 / 2,000
- **Correctness:** Where both `PERMIT_DATE` and `IssueDate` exist (1,604), they always match. Gaps are rows with blank Issued.
- **Fillable:** 2 Active (`Issued`) rows remapped from missing/In Review had blank `PERMIT_DATE` but populated `IssueDate`
- **Spurious:** 1 In Review row (`SERSS2024-0128`, remapped from Active) carried `PERMIT_DATE` with blank `IssueDate` → cleared
- **Repair:** **2 FILLED**, **1 FIXED** · missing after: 394
- Post-repair coverage: Active 100% (669/669); Final 78.1% (857/1,097)
- **Not fillable:** 240 Final rows (142 `Final` + 98 `Closed`) with blank `IssueDate` — mostly Residential Building Reports and Encroachment / trade shells that never recorded an issue date

### FINAL_DATE

- **Missing before:** 776 / 2,000
- **Correctness:** Where both exist (1,222), they always match `entity.FinalDate`. Non-Final rows incorrectly carried `FINAL_DATE` (6 Active, 134 Inactive), including 2 Issued rows whose stale `STATUS_ORIGINAL=final` left a `FINAL_DATE` with no FinalDate in DATA.
- **Fillable Final gaps:** 7 from `FinalDate`/`FinalizeDate` (including remapped-to-Final rows) + 5 from Approved inspections whose description contains `Final` (e.g. `2620 Final Building`, `301 Final Public Works`)
- **Repair:** **12 FILLED**, **140 FIXED** (cleared non-Final) · missing after: 904
- Post-repair: Final 99.9% (1,096 / 1,097); Active / In Review / Inactive all 0%
- **Not fillable:** 1 Closed Residential Building Report (`R2005-1376`) with neither FinalDate nor usable finaling inspections

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 2 | 12 | 2 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 2 | 1 | 395 | 394 |
| FINAL_DATE | 12 | 140 | 776 | 904 |

Root cause of status errors: pipeline normalized from `STATUS_ORIGINAL` (often an earlier lifecycle label like `issued` or `final`) rather than current `entity.CaseStatus`. Date fields that were populated were already consistent with DATA; remaining Final `PERMIT_DATE` gaps reflect blank Issued fields on closed report/encroachment shells, not mapping bugs. Net `FINAL_DATE` missing rises because clearing spurious non-Final dates outweighs the 12 Final fills.
