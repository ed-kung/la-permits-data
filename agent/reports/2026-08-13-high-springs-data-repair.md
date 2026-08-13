# High Springs (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (sorted `(STATE, JURISDICTION)` order) was **High Springs**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`). Upstream left blank `Status:` and `Response Required` unmapped (32 nulls), often copied latest Plan Review Completion into FILE_DATE instead of earliest Review Start, never populated FINAL_DATE, and already had correct PERMIT_DATE whenever `Permit Details["Issue Date:"]` was present. Repair FILLED 30 STATUS values (2 empty historic shells remain null). FILE_DATE FIXED 141 / FILLED 9. PERMIT_DATE unchanged (0 FILLED / 0 FIXED). FINAL_DATE FILLED 1,281 Closed/inferred-Final shells with real Final*/CO stamps (86.9% of Final).

## Jurisdiction selection

Unique `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked in sorted order against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **High Springs, FL** → `agent/scripts/fl/data_repair_fl_high_springs.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share portal keys `Status:`, `Permit #:`, `Issue Date` (always null), `Permit Details`, `Inspections`, `Reviews`. Key-set prefixes reflect permit-form extras:

| Schema prefix | Distinguishing extras |
| --- | --- |
| `portal_building` | Foundation / flood / meter-release building fields |
| `portal_roof` | Roofing product-approval fields |
| `portal_mech` | HVAC / mechanical unit fields |
| `portal_sign` | Sign type / acreage fields |
| `portal_electric` | Temp power / service-upgrade fields |
| `portal_form` | Generic `Type of Work` form |
| `portal_core` | Minimal core permit keys |

Content suffixes split by recoverable dates (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`). Largest buckets: `portal_building_issued_finaled` (530), `portal_roof_issued_finaled` (295), `portal_form_issued_finaled` (174), `portal_mech_issued_finaled` (172).

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (blank/unmapped inferred from usable Issue Date / Final* stamps) |
| FILE_DATE | Earliest non-certificate Review Start on/before Issue → else earliest Review Completion on/before Issue |
| PERMIT_DATE | `Permit Details["Issue Date:"]` for Active / Final / Inactive |
| FINAL_DATE | Latest passed Final*/CO inspection (blank Status + real date on a Final* type counts); Final only |

Status map: Closed → Final; Issued / Approved → Active; Under Review / Online Application Received / Response Required → In Review; Canceled / Denied / Abandoned → Inactive. In Review shells that already carry a usable Issue Date are upgraded to Active (none in this sample).

## Field assessments

### STATUS_NORMALIZED

| Status: | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 1,471 | Final 1,471 | Correct |
| Issued | 342 | Active 342 | Correct |
| Canceled | 54 | Inactive 54 | Correct |
| Approved | 43 | Active 43 | Correct |
| Under Review | 42 | In Review 42 | Correct |
| (blank) | 28 | null 28 | Empty/historic; 23→Active (Issue Date), 3→Final (Final* stamp), 2 stay null |
| Denied | 9 | Inactive 9 | Correct |
| Online Application Received | 5 | In Review 5 | Correct |
| Response Required | 4 | null 4 | Unmapped → In Review |
| Abandoned | 2 | Inactive 2 | Correct |

**Root causes:**
- **Unmapped Status values:** `Response Required` and blank `Status:` were absent from the upstream normalizer (32 nulls).
- **Blank Status with Issue / Final stamps:** 26 of 28 empty-Status shells still carry `Permit Details["Issue Date:"]` (mostly older mechanical/plumbing/roofing permits); 3 also have a passed Final* inspection.

**Repair performance:** FILLED 30, FIXED 0; missing 32 → 2. After: Final 1,474; Active 408; Inactive 65; In Review 51; null 2 (`PL000437`, `BD003386` — blank Status, no Issue Date, empty Reviews/Inspections).

### FILE_DATE

Ideal: populated for all records.

- Only 166 / 2,000 rows had FILE_DATE before repair; all of those had non-empty `Reviews`.
- Upstream FILE_DATE matched the **latest Review Completion** on 165 / 166 populated rows — i.e. plan-review finish, not application/submittal. High Springs has no Application Intake task (337 Review rows are almost entirely `Plan Review`).
- Correct source is **earliest Review Start** on/before Issue (172 rows), else earliest Review Completion (1 additional row).
- **141 FIXED** from latest Completion → earliest Start; **9 FILLED** where FILE was null but a Review Start/Completion existed.
- Post-issue FILE values with no application source are cleared (eliminates FILE > PERMIT inversions).

Coverage after repair: Active 11.3%; Final 7.7%; In Review 17.6%; Inactive 6.2%. Remaining gaps are mostly older shells with empty `Reviews` (1,825 rows have no recoverable Review dates). Missing 1,834 → 1,827.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Top-level `Issue Date` is always null; usable stamp is `Permit Details["Issue Date:"]` (1,791 rows).
- Existing PERMIT_DATE values already matched Issue Date (**0 calendar mismatches**; **0 FILLED / 0 FIXED**).
- No In Review rows carried a spurious PERMIT_DATE to clear.

Coverage after repair: Active 369/408 (90.4%); Final 1,413/1,474 (95.9%); In Review 0/51; Inactive 9/65. Active/Final still missing PERMIT_DATE: 100 (Closed 61, Approved 38, Issued 1) — blank Issue Date only; Approved-without-Issue is expected for not-yet-issued shells.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- **Every sample row had FINAL_DATE null** before repair.
- **1,281 FILLED** from passed Final*/CO inspections, including blank-Status Final* rows that still carry a calendar date (e.g. `25 Building Final`).
- Non-Final correctly have no FINAL_DATE after repair.

Coverage after repair: Final 1,281/1,474 (86.9%); Active / In Review / Inactive 0%. Still missing FINAL on 193 Closed rows (102 with empty Inspections; others lack a usable Final*/CO pass). Date-order: FILE>PERMIT 0, FILE>FINAL 0, PERMIT>FINAL 2 (`EL000228`, `BD003425` — source quirks where Final insp predates Issue Date).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 30 | 0 | 32 → 2 |
| FILE_DATE | 9 | 141 | 1,834 → 1,827 |
| PERMIT_DATE | 0 | 0 | 209 → 209 |
| FINAL_DATE | 1,281 | 0 | 2,000 → 719 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_high_springs.py` (`data_repair`)
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_fl_high_springs_repaired.parquet`
