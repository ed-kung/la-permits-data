# Pleasant Hill (CA) data repair

**Summary:** Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for 2,000 Pleasant Hill sample records against the Tyler EnerGov DATA JSON. The main defect was 915 rows with CaseStatus `No Action Taken` left as missing STATUS_NORMALIZED; most are issued legacy shells, and 448 have Passed Final Building / trade-completion evidence and were remapped to Final. FILE_DATE and PERMIT_DATE already matched ApplyDate / IssueDate. Spurious FINAL_DATE on 75 Inactive Expired/Void rows was cleared, and FINAL_DATE was filled for 426 newly Final rows from inspection dates (plus 2 Issued→Final catch-ups). Script: `agent/scripts/ca/data_repair_ca_pleasant_hill.py`.

## Data shape

| Schema | Count | Top-level keys |
| --- | ---: | --- |
| `entity_fees` | 1,954 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 46 | above + reviews, holds, attachments, more_info |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` / `details.FinalizeDate`, with Passed `processing_status` Final* inspections as a FINAL_DATE fallback.

## Field assessment

### STATUS_NORMALIZED

| STATUS_ORIGINAL | Before STATUS_NORMALIZED | n |
| --- | --- | ---: |
| no action taken | *(missing)* | 915 |
| complete | Final | 576 |
| issued | Active | 283 |
| expired / void / withdrawn | Inactive | 189 |
| in review / submitted / fees due / submitted - online / on hold | In Review | 37 |

- Upstream never mapped `No Action Taken` (nearly all are older issued permits, mostly 1990–2010, with `details.Issued=True` and IssueDate).
- One Issued row had `PermitStatus=Complete` and FinalizeDate while STATUS stayed Active.
- Other CaseStatus values already matched the normalized mapping.

### FILE_DATE

- 0 missing; all 2,000 match `entity.ApplyDate` at day resolution. No repair needed.

### PERMIT_DATE

- 54 missing: all In Review (37) or pre-issuance Inactive (16) plus 1 unissued `No Action Taken` — correctly empty.
- When present, every PERMIT_DATE matches IssueDate. Active/Final coverage is 100% after status repair (IssueDate already populated on those shells).

### FINAL_DATE

- All 576 `Complete` / Final rows already had FINAL_DATE matching FinalDate/FinalizeDate.
- 75 Inactive (73 Expired, 2 Void) carried FINAL_DATE from `entity.FinalDate` as a case-closure stamp — incorrect for non-Final status.
- `No Action Taken` rows with Passed Final Building (or trade-permit Final*) lacked FINAL_DATE despite completion evidence.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 915 | 2 | 915 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 54 → 54 |
| FINAL_DATE | 428 | 75 | 1,349 → 996 |

Status after repair: Final 1,026 · Active 747 · Inactive 189 · In Review 38.

`No Action Taken` disposition: Final 448 · Active 466 · In Review 1 (unissued SDP-23-0001).

Active / Final PERMIT_DATE coverage: 100%. Final FINAL_DATE coverage: 1,004 / 1,026 (97.9%). The 22 Final rows without FINAL_DATE have Passed Final Building inspections dated in 1900 (sentinel), rejected by the 1990–2035 date window.

## Notes / limitations

- Building permits with only trade Final inspections (no Final Building) stay Active — partial finals are not treated as completion.
- 168 PERMIT > FINAL day inversions appear after filling FINAL_DATE from inspections on legacy `No Action Taken` rows; IssueDate on many of those shells looks like a mid-2000s migration stamp later than the real inspection dates. One such inversion already existed on a Complete row before repair.
- ExpireDate is not used as a completion date.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_pleasant_hill.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_pleasant_hill_repaired.parquet`
