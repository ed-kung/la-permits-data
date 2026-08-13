# Treasure Island (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Treasure Island**. DATA is a Tyler EnerGov payload (`entity` / `details` / `fees` / `processing_status`). Upstream left 20 rows with null `STATUS_NORMALIZED` for unmapped review-workflow CaseStatus values, and 6 rows where `STATUS_ORIGINAL` lagged live CaseStatus (Complete→Active/Inactive, Expired→Active). `FILE_DATE` already matched `ApplyDate` on all 2,000 rows. Repair filled/fixed all statuses, cleared 20 spurious In Review `PERMIT_DATE` values plus 5 EnerGov `1900-01-01` IssueDate sentinels, cleared 243 Final `FINAL_DATE` sentinels and 4 non-Final finals, and filled FinalDate on 4 mislabeled Complete shells. After repair: STATUS 100%; FILE_DATE 100%; Active PERMIT_DATE 74.6%; Final PERMIT_DATE 99.5%; Final FINAL_DATE 85.7% (residual gaps are blank IssueDate / 1900-only FinalDate with no alternate in DATA).

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Treasure Island, FL** → `agent/scripts/fl/data_repair_fl_treasure_island.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows are EnerGov. Two key-set prefixes, with content suffixes by which canonical dates are present:

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,461 | Apply + Issue + Final |
| `energov_issued` | 376 | Apply + Issue, no Final |
| `energov_applied` | 113 | Apply only |
| `energov_full_applied` | 34 | extras + Apply only |
| `energov_full_issued` | 10 | extras + Issue |
| `energov_finaled` | 5 | Apply + Final, no Issue |
| `energov_full_issued_finaled` | 1 | extras + Issue + Final |

`energov_full_*` adds `reviews` / `holds` / `attachments` / `more_info` (45 rows).

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` / `details.ApplyDate` |
| PERMIT_DATE | `entity.IssueDate` / `details.IssueDate` |
| FINAL_DATE | `entity.FinalDate` / `details.FinalizeDate`; else passed final-ish `processing_status` inspection |

CaseStatus → normalized: Complete / Closed → Final; Issued / Reinstated → Active; In Review / Submitted / Submitted - Online / Ready to Issue / Incomplete Application / Waiting on Response to Review Comments / Waiting on Water & Nav Permit / Review(s) Complete* / Tabled → In Review; Expired / Void / Denied / Withdrawn → Inactive.

## Field assessments

### STATUS_NORMALIZED

| CaseStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Complete | 1,697 | Final (1,693); Active (3); Inactive (1) | Fix 4 stale → Final |
| Expired | 86 | Inactive (84); Active (2) | Fix 2 stale → Inactive |
| Issued | 71 | Active | Correct |
| In Review | 55 | In Review | Correct |
| Void | 28 | Inactive | Correct |
| Submitted | 19 | In Review | Correct |
| Waiting on Response to Review Comments | 14 | **null** | Fill → In Review |
| Submitted - Online | 10 | In Review | Correct |
| Ready to Issue | 8 | In Review | Correct |
| Incomplete Application | 6 | In Review | Correct |
| Waiting on Water & Nav Permit | 2 | **null** | Fill → In Review |
| Review(s) Complete / - Complete / - Needs Corrections | 1 each | **null** | Fill → In Review |
| Tabled | 1 | **null** | Fill → In Review |

**Root cause:** Upstream mapped common `STATUS_ORIGINAL` strings but (1) left several review-workflow CaseStatus values unmapped → 20 nulls, and (2) did not refresh when CaseStatus advanced to Complete/Expired while STATUS_ORIGINAL still said issued/expired → 6 mismatches. The three Complete→Active rows and one Complete→Inactive row all already carry real `FinalDate` in DATA.

**Repair performance:** FILLED 20, FIXED 6; missing 20 → 0. After: Final 1,697; In Review 118; Inactive 114; Active 71.

### FILE_DATE

Ideal: populated for all records.

- Before: present on **2,000 / 2,000**; every value matches `entity.ApplyDate` at day resolution.
- **0 FILLED, 0 FIXED.** Coverage remains 100% across all statuses.
- `FILE_DATE > PERMIT_DATE` inversions after repair: 34 (source EnerGov ApplyDate after IssueDate; not rewritten).

### PERMIT_DATE

Ideal: populated for Active and Final.

- Present IssueDate values already matched stored `PERMIT_DATE` (0 calendar mismatches) whenever both were usable.
- **20 FIXED:** cleared spurious `PERMIT_DATE` on In Review shells that still carried `IssueDate` (legacy Issued=true, CaseStatus still In Review, mostly 1995–2003).
- **5 FIXED:** cleared EnerGov `1900-01-01` IssueDate sentinels stored as PERMIT_DATE on Complete shells (no replacement IssueDate).
- **0 FILLED.** Missing rose 147 → 172 from those clears.
- Residual Active/Final gaps: **18 Issued** + **9 Complete** with blank/sentinel `IssueDate` (`details.Issued=false` on the Issued shells) — not repairable from DATA.

Coverage after repair: Active 53/71 (74.6%); Final 1,688/1,697 (99.5%); In Review 0/118; Inactive 87/114 (76.3%, retained when issued).

### FINAL_DATE

Ideal: populated for Final records.

- Usable FinalDate values already matched stored `FINAL_DATE` (0 calendar mismatches).
- **243 FIXED:** cleared EnerGov `1900-01-01` FinalDate sentinels on Complete shells (no `CompleteDate` / `ClosedDate` / usable `processing_status` fallback).
- **4 FIXED:** cleared real FinalDate values on non-Final shells (Issued 2, In Review 1, Void 1).
- **4 FILLED:** FinalDate written after Complete→Final status fixes where FINAL_DATE was previously null.
- Missing rose 303 → 546 because sentinel clears dominate; residual Final gaps: **243 Complete** with only the 1900 sentinel — not repairable from DATA.

Coverage after repair: Final 1,454/1,697 (85.7%); Active / In Review / Inactive all 0%. `PERMIT_DATE > FINAL_DATE` after repair: 7 (source inversions).

## Artifacts

| Path | Description |
| --- | --- |
| `agent/scripts/fl/data_repair_fl_treasure_island.py` | `data_repair()` implementation + CLI stats |
| `$AGENT_DATA_PATH/repaired/permits_fl_treasure_island_repaired.parquet` | Repaired 2,000-row sample with flag + `INFERRED_SCHEMA` columns |
