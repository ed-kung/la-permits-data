# Surfside (FL) data repair

Surfside was the first `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing repair script. Its DATA column is a Tyler EnerGov payload. Ten `STATUS_NORMALIZED` values were stale relative to live `entity.CaseStatus`; `FILE_DATE` already matched `ApplyDate` for all 2,000 rows; `PERMIT_DATE` and `FINAL_DATE` needed fills after status fixes plus clearing of values on non-applicable statuses. Large residual gaps remain where EnerGov itself lacks `IssueDate` / `FinalDate`.

## Scope

- Sample: 2,000 Surfside, FL rows from `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Script: `agent/scripts/fl/data_repair_fl_surfside.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_surfside_repaired.parquet`

## DATA schema

Two key-set variants, both EnerGov:

| Schema prefix | n | Notes |
| --- | ---: | --- |
| `energov_*` | 1,979 | `contacts`, `details`, `entity`, `fees`, `processing_status` |
| `energov_full_*` | 21 | same plus `reviews` / `holds` / `attachments` / `more_info` |

Content suffixes reflect recoverable dates (`issued_finaled`, `issued`, `finaled`, `applied`). Observed distribution after classification: `energov_issued` 1,032; `energov_applied` 829; `energov_issued_finaled` 116; plus small `energov_full_*` / `energov_finaled` counts.

Canonical sources:

- Status ← `entity.CaseStatus` (equals `details.PermitStatus` on all rows)
- File date ← `entity.ApplyDate`
- Permit date ← `entity.IssueDate`
- Final date ← `entity.FinalDate` / `details.FinalizeDate`, else passed final-ish `processing_status` inspection (rarely usable here)

## Field assessment

### STATUS_NORMALIZED

No nulls. Mapping from `CaseStatus` is otherwise consistent (`Complete`→Final, `Issued`→Active, fee/submit/hold states→In Review, `Expired`/`Void`/`Denied`/`Plan Approval Expired`→Inactive), but **10 rows** used a stale `STATUS_ORIGINAL` instead of live `CaseStatus`:

| before → after | n | Cause |
| --- | ---: | --- |
| In Review → Active | 3 | `Issued` cases still labeled from fees due / submitted |
| Active → Final | 2 | `Complete` still labeled issued |
| Inactive → Final | 2 | `Complete` still labeled expired |
| Active → Inactive | 2 | `Expired` still labeled issued |
| In Review → Inactive | 1 | `Expired` still labeled fees paid |

Repair: **0 FILLED, 10 FIXED**. All statuses mapped; none left null.

### FILE_DATE

Already populated for every row and identical to `ApplyDate` at day resolution. **0 FILLED, 0 FIXED.** Coverage remains 100% across all statuses.

### PERMIT_DATE

Ideal: populated for Active and Final (and retained for Inactive when issued).

- **3 FILLED**: Issued shells previously labeled In Review, after status upgrade to Active.
- **19 FIXED**: cleared spurious `PERMIT_DATE` on In Review (`Fees Due` / `Fees Paid` / `In Review`).
- Missing count rose slightly (850 → 866) because clears outnumbered fills.
- After repair: Active 82/176 (46.6%), Final 135/696 (19.4%), In Review 0/146, Inactive 917/982 (93.4%).
- **Not repairable:** 94 Issued and 561 Complete rows have blank `IssueDate` (`details.Issued=false`) — typically older shells.

### FINAL_DATE

Ideal: populated for Final only.

- **4 FILLED**: Complete shells previously Active/Inactive that already carried `FinalDate`.
- **16 FIXED**: cleared `FINAL_DATE` on non-Final rows (Issued, Expired, Plan Approval Expired, Fees Paid).
- Missing count rose (1,894 → 1,906) from those clears.
- After repair: Final 94/696 (13.5%); Active / In Review / Inactive all 0%.
- **Not repairable:** 602 Complete rows lack `FinalDate`/`FinalizeDate`. `processing_status` is usually empty; when present it is mostly unlabeled “Legacy Inspection”, so it does not yield a final date.

## Repair performance summary

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 10 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 3 | 19 | 850 | 866 |
| FINAL_DATE | 4 | 16 | 1,894 | 1,906 |

Post-repair sanity: `STATUS_NORMALIZED` fully determined by `CaseStatus`; no date sentinels remain; `PERMIT_DATE > FINAL_DATE` inversions = 0; one residual `FILE_DATE > PERMIT_DATE` inversion is present in source EnerGov dates on an Expired row and is preserved.
