# Winter Park (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Winter Park**. DATA is a Tyler EnerGov payload (`entity` / `details` / `fees` / `processing_status`). Upstream left 30 rows with null `STATUS_NORMALIZED` for unmapped CaseStatus values (`Address Approved`, `Process For Issuance`, `Permit Application Expired`); otherwise status already matched live CaseStatus. `FILE_DATE` already matched `ApplyDate` on all 2,001 rows. Repair filled those 30 statuses, cleared 11 spurious In Review `PERMIT_DATE` values and 99 non-Final `FINAL_DATE` values. After repair: STATUS 100%; FILE_DATE 100%; Active PERMIT_DATE 100%; Final PERMIT_DATE 99.6%; Final FINAL_DATE 100%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Winter Park, FL** → `agent/scripts/fl/data_repair_fl_winter_park.py` (2,001 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows are EnerGov. Two key-set prefixes, with content suffixes by which canonical dates are present:

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,279 | Apply + Issue + Final |
| `energov_issued` | 367 | Apply + Issue, no Final |
| `energov_applied` | 158 | Apply only |
| `energov_finaled` | 69 | Apply + Final, no Issue |
| `energov_full_issued` | 69 | extras + Issue |
| `energov_full_applied` | 46 | extras + Apply only |
| `energov_full_issued_finaled` | 7 | extras + Issue + Final |
| `energov_full_finaled` | 6 | extras + Final, no Issue |

`energov_full_*` adds `reviews` / `holds` / `attachments` / `more_info` (128 rows).

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (equals `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` / `details.ApplyDate` |
| PERMIT_DATE | `entity.IssueDate` / `details.IssueDate` |
| FINAL_DATE | `entity.FinalDate` / `details.FinalizeDate`; else passed final-ish `processing_status` inspection |

CaseStatus → normalized: Complete / Closed / Address Approved → Final; Issued / Reinstated → Active; In Review / On Hold / Fees Due / Submitted - Online / Stop Work Order / Process For Issuance → In Review; Expired / Void / Denied / Permit Application Expired → Inactive.

## Field assessments

### STATUS_NORMALIZED

| CaseStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Complete | 1,175 | Final | Correct |
| Issued | 270 | Active | Correct |
| Expired | 242 | Inactive | Correct |
| Void | 153 | Inactive | Correct |
| In Review | 57 | In Review | Correct |
| Fees Due | 36 | In Review | Correct |
| Closed | 13 | Final | Correct |
| Permit Application Expired | 13 | **null** | Fill → Inactive |
| Process For Issuance | 11 | **null** | Fill → In Review |
| Denied | 10 | Inactive | Correct |
| Address Approved | 6 | **null** | Fill → Final (all have FinalDate) |
| On Hold / Submitted - Online | 6 each | In Review | Correct |
| Stop Work Order | 2 | In Review | Correct |
| Reinstated | 1 | Active | Correct |

**Root cause:** Upstream mapped from `STATUS_ORIGINAL` for common statuses but left three CaseStatus strings unmapped → 30 nulls. No stale Active/Final/In Review mismatches vs live CaseStatus.

**Repair performance:** FILLED 30, FIXED 0; missing 30 → 0. After: Final 1,194; Inactive 418; Active 271; In Review 118.

### FILE_DATE

Ideal: populated for all records.

- Before: present on **2,001 / 2,001**; every value matches `entity.ApplyDate` at day resolution.
- **0 FILLED, 0 FIXED.** Coverage remains 100% across all statuses.
- `FILE_DATE > PERMIT_DATE` inversions after repair: 0.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Present IssueDate values already matched stored `PERMIT_DATE` (0 calendar mismatches) for Complete / Issued / Closed / Expired / Address Approved.
- **11 FIXED:** cleared spurious `PERMIT_DATE` on In Review shells that still carried `IssueDate` (`Fees Due` 7, `In Review` 3, `Stop Work Order` 1) — post-issuance fee/review states kept as In Review per EnerGov convention.
- **0 FILLED.** Missing rose 279 → 290 from those clears.
- Residual Active/Final gaps: **5 Complete** rows with blank `IssueDate` (`details.Issued=false`) — not repairable from DATA.

Coverage after repair: Active 271/271 (100%); Final 1,189/1,194 (99.6%); In Review 0/118; Inactive 251/418 (60.0%, retained when issued).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All Complete / Closed rows already matched `entity.FinalDate` / `details.FinalizeDate` (0 mismatches); Address Approved already had FINAL_DATE.
- **99 FIXED:** cleared `FINAL_DATE` on non-Final shells (Void 74, Issued 18, Fees Due 2, Permit Application Expired 2, Reinstated 1, Stop Work Order 1, Denied 1) where EnerGov still exposed FinalDate/FinalizeDate.
- Final coverage after repair: **1,194 / 1,194 (100%)**; Active / In Review / Inactive 0%.
- Nine residual `PERMIT_DATE > FINAL_DATE` inversions are present in source EnerGov dates (mostly address-change shells where IssueDate is after FinalizeDate) and are preserved.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 30 | 0 | 30 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 11 | 279 → 290 |
| FINAL_DATE | 0 | 99 | 708 → 807 |

Remaining structural gaps: 5 Final rows without `IssueDate` → no PERMIT_DATE. Missing-count increases for PERMIT_DATE / FINAL_DATE are intentional clears of values that do not apply to In Review / non-Final statuses.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_winter_park.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_winter_park_repaired.parquet`
