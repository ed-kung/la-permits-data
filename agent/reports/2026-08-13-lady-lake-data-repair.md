# Lady Lake (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-appearance order) was **Lady Lake**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`) plus a flat unsuffixed variant (`Status`, `Permit #`, `Issue Date`). Upstream left 12 statuses unmapped (`Additional Information Needed`, `Revise and Resubmit`, `Closed no inspections`, `Almost Expired`). `FILE_DATE` was often the latest Review Completion (including post-issue Online Document Upload) rather than Application Intake. `PERMIT_DATE` already matched `Permit Details["Issue Date:"]` / date-like flat `Issue Date` whenever present. `FINAL_DATE` was missing on every row; repair filled 187 Closed/CO shells with passed Final*/CO inspections. After repair: STATUS 100%; FILE_DATE ~14% overall; Active PERMIT_DATE 99.4%; Final FINAL_DATE 10.8%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Lady Lake, FL** → `agent/scripts/fl/data_repair_fl_lady_lake.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

Two structural families:

1. **Portal (1,888 rows):** colon keys `Status:`, `Permit #:`, `Permit Details`, `Reviews`, `Inspections`. Top-level `Issue Date` is usually null or polluted with work-description text; usable issue stamp is `Permit Details["Issue Date:"]`.
2. **Flat (112 rows):** unsuffixed `Status`, `Permit #`, `Issue Date`, `Permit Type`, `Sub Type` (no Reviews / Inspections / Permit Details). `Issue Date` is date-like on 88 rows and matches upstream `PERMIT_DATE`.

Key-set prefixes further split portal rows by form extras:

| Schema prefix | Distinguishing extras |
| --- | --- |
| `portal_res` | Residential form fields (`Demo RES`, `Dimensions RES`, …) |
| `portal_com` | Commercial form fields (`Roof Type COM`, `Site Plan COM`, …) |
| `portal_migrated` | Migrated Permit / contact / zone shells |
| `portal_core` | Minimal colon-key portal shell |
| `portal_flat` | Unsuffixed Status / Permit # / Issue Date only |

Content suffixes split by recoverable dates (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`). Largest buckets: `portal_migrated_issued` (1,473), `portal_res_issued_finaled` (141), `portal_res_issued` (91), `portal_flat_issued` (88).

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status:` / flat `Status` (blank/unmapped inferred from Issue / Final* stamps) |
| FILE_DATE | Application Intake Start/Completion (≤ Issue); else earliest non-post-issuance Review Start/Completion (≤ Issue) |
| PERMIT_DATE | `Permit Details["Issue Date:"]` or date-like top-level / flat `Issue Date` |
| FINAL_DATE | Latest passed Final*/CO inspection; Final only |

Status map: Closed / Closed no inspections / Certificate of Occupancy → Final; Issued / Approved / Almost Expired → Active; Under Review / Pending Payment / Online Application Received / Additional Information Needed / Revise and Resubmit → In Review; Withdrawn / Abandoned / Expired → Inactive. In Review shells that already carry a usable Issue Date are upgraded to Active (none in this sample).

## Field assessments

### STATUS_NORMALIZED

| Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 1,718 | Final | Correct (incl. 47 flat) |
| Issued | 162 | Active | Correct (incl. 37 flat) |
| Under Review | 43 | In Review | Correct |
| Withdrawn | 38 | Inactive | Correct |
| Abandoned | 7 | Inactive | Correct |
| Certificate of Occupancy | 7 | Final | Correct |
| Pending Payment | 7 | In Review | Correct |
| Expired | 4 | Inactive | Correct |
| Approved | 1 | Active | Correct |
| Online Application Received | 1 | In Review | Correct |
| Closed no inspections | 5 | **null** | Unmapped → Final |
| Additional Information Needed | 3 | **null** | Unmapped → In Review |
| Revise and Resubmit | 3 | **null** | Unmapped → In Review |
| Almost Expired | 1 | **null** | Unmapped → Active |

**Root cause:** Upstream normalizer omitted four portal Status labels (12 nulls). Mapped statuses were already correct; no FIXED status changes.

**Repair performance:** FILLED 12, FIXED 0; missing 12 → 0. After: Final 1,730; Active 164; In Review 57; Inactive 49.

### FILE_DATE

Ideal: populated for all records.

- Before: missing on **1,718 / 2,000**. Present values clustered on modern rows with non-empty `Reviews`.
- Upstream often copied the **latest Review Completion**, including post-issue `Online Document Upload` (132 of 282 populated rows matched max Completion). Correct source is **Application Intake** (280 rows have that task), else earliest non-post-issuance Review Start/Completion on/before Issue.
- **187 FIXED** to intake / early-review stamps; **4 FILLED** where FILE was null but a review source existed; **4 FIXED clears** of post-issue FILE values with no usable application source.
- Flat shells and most migrated Closed shells have empty/absent Reviews → FILE_DATE stays missing.

Coverage after repair: Active 101/164 (61.6%); Final 149/1,730 (8.6%); In Review 19/57 (33.3%); Inactive 13/49 (26.5%). Overall 282/2,000 (14.1%). Missing 1,718 → 1,718 (fills offset by clears). FILE>PERMIT / FILE>FINAL inversions: 0.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Portal issue stamp is `Permit Details["Issue Date:"]` (1,793 rows); flat date-like `Issue Date` adds 88.
- Existing PERMIT_DATE already matched those stamps (**0 calendar mismatches**; **0 FILLED / 0 FIXED**).
- No In Review rows carried a spurious PERMIT_DATE to clear.

Coverage after repair: Active 163/164 (99.4%); Final 1,705/1,730 (98.6%); In Review 0/57; Inactive 13/49. Active/Final still missing PERMIT_DATE: 26 (Closed 25 cash-receipt/migrated shells with blank Issue Date; Approved 1 not-yet-issued).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- **Every sample row had FINAL_DATE null** before repair.
- **187 FILLED** from passed Final*/CO inspections (including `Pass` + “View Comments” statuses), covering Closed and Certificate of Occupancy rows.
- Non-Final correctly have no FINAL_DATE after repair.
- Remaining Final gaps (1,543) are mostly Closed / Closed no inspections shells with empty Inspections or only `OTHER *` inspection types (no Final*/CO stamp). Flat Final shells have no Inspections at all.

Coverage after repair: Final 187/1,730 (10.8%); Active / In Review / Inactive 0%. PERMIT>FINAL inversions: 1 (`ROOF17-00001570` — Final Building/Roof insp 2018-01-24 precedes Issue Date 2018-01-29; source quirk left as-is).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 12 | 0 | 12 → 0 |
| FILE_DATE | 4 | 191 | 1,718 → 1,718 |
| PERMIT_DATE | 0 | 0 | 119 → 119 |
| FINAL_DATE | 187 | 0 | 2,000 → 1,813 |

Remaining structural gaps: FILE_DATE on older/migrated/flat shells (no Application Intake / Reviews); Final PERMIT_DATE on blank-Issue cash-receipt shells; Final FINAL_DATE when Inspections lack a Final*/CO pass.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_lady_lake.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_lady_lake_repaired.parquet`
