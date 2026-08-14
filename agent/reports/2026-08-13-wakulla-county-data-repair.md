# Wakulla County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Wakulla County**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`). Upstream left `HOLD STATUS` unmapped (38 nulls); repair fills those and upgrades 10 Issued + 9 HOLD rows with Final Building / CO to Final. `FILE_DATE` often copied Issue Date (Inspection Checklist) or latest Review Completion instead of Plan Review Start — repair rewrites 520, fills 26, and clears 515 checklist/issue copies. `PERMIT_DATE` already matched `Permit Details["Issue Date:"]` on all comparable rows (0 changes). `FINAL_DATE` was missing on every row; filled from Final*/CO inspections or `Bldg - Final Review` Completion for Final rows. After repair: STATUS 0 null; FILE_DATE 35.0%; Active/Final PERMIT_DATE 1,696/1,720 (98.6%); Final FINAL_DATE 1,040/1,245 (83.5%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in file order. Wakulla County was the first pair without `agent/scripts/fl/data_repair_fl_wakulla_county.py`.

## DATA shape

All 2,000 rows share the same CitizenServe portal shell. Form extras vary; inferred schema prefixes:

| Schema prefix | n | Role |
| --- | ---: | --- |
| `portal_form_residential` | 1,118 | Dwelling / sqft / contractor form extras |
| `portal_form_changeout` | 528 | Window / roof / HVAC change-out extras |
| `portal_core` | 239 | Minimal colon-key shell |
| `portal_core_select` | 84 | Core + `Select One` |
| `portal_core_extra` | 31 | Sparse non-form extras |

Suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) mark which canonical dates are recoverable.

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (`Closed`→Final, `Issued`/`Approved`→Active, `Under Review`/`Ready for Payment`→In Review, `Permit Expired`/`Void`→Inactive; `HOLD STATUS` inferred from Issue / primary Final) |
| FILE_DATE | Earliest Plan Review Start/Completion ≤ Issue; else other non-checklist / non-final-review Review dates |
| PERMIT_DATE | `Permit Details["Issue Date:"]` (top-level `Issue Date` always null) |
| FINAL_DATE | Latest passed Final*/CO inspection, else `Bldg - Final Review` Completion (floored at Issue) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,226; Active 459; Inactive 240; In Review 37; **38 null** (all `HOLD STATUS`).
After: Final 1,245; Active 475; Inactive 240; In Review 40; **0 null**.

| Status: | n | Upstream STATUS_NORMALIZED | After repair |
| --- | ---: | --- | --- |
| Closed | 1,226 | Final | Final |
| Issued | 421 | Active | Active 411 / Final 10 |
| Permit Expired | 169 | Inactive | Inactive |
| Void | 71 | Inactive | Inactive |
| Approved | 38 | Active | Active |
| HOLD STATUS | 38 | null | Active 22 / Final 9 / In Review 7 |
| Under Review | 31 | In Review | In Review 29 / Active 2 |
| Ready for Payment | 6 | In Review | In Review 4 / Active 2 |

Issued / HOLD rows with a passed primary Final Building / Certificate of Occupancy (or Completion) inspection are upgraded to Final. In Review labels that already carry Issue Date become Active. Flags: **38 FILLED, 14 FIXED**.

### FILE_DATE

Missing on 812/2,000 before. When present, calendar day often matched Issue Date (644/1,188) via `Bldg - Inspection Checklist`, or latest Review Completion — not Plan Review Start. No Application Intake tasks exist; Checklist and Final Review are excluded as FILE sources.

| Repair action | n |
| --- | ---: |
| FIXED to Plan Review / earliest early Review (≤ Issue) | 520 |
| Cleared Issue-Date copies / post-issue FILE with no application source | 515 |
| FILLED from Plan Review / early Reviews | 26 |
| Still missing (empty Reviews or checklist-only shells) | 1,301 |

After: **699/2,000 (35.0%)** populated; 0 `FILE_DATE > PERMIT_DATE` inversions. Coverage falls because clearing incorrect Issue-Date copies is preferred over retaining a false application date.

### PERMIT_DATE

Missing on 118/2,000 before. Every populated `PERMIT_DATE` already matched `Permit Details["Issue Date:"]` (1,882/1,882); no `01/01/2000` sentinel. Top-level `Issue Date` is null on all rows. No FILLED/FIXED changes. Still missing: 19 Approved + 5 Closed shells with blank Issue Date (plus Inactive voids/expired without Issue). Active/Final coverage: **1,696/1,720 (98.6%)**. In Review correctly has 0 PERMIT_DATE after status upgrades removed the few pre-issuance rows that had Issue Date.

### FINAL_DATE

Missing on 2,000/2,000 before. Portal inspection types include rich Final* / CO labels (`Final Certificate of Occupancy`, `Final Building Inspection`, trade finals, etc.).

| Repair action | n |
| --- | ---: |
| FILLED from Final*/CO inspection or Final Review Completion (Final only) | 1,040 |

Final rows still missing FINAL_DATE (205 Closed): 144 empty Inspections, 58 with passed non-Final trade inspections only, 3 with no passed inspection. Ideal Final coverage: **1,040/1,245 (83.5%)**. Non-Final rows keep FINAL_DATE cleared. 0 `PERMIT_DATE > FINAL_DATE` inversions.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 38 | 14 | 38 → 0 |
| FILE_DATE | 26 | 1,035 | 812 → 1,301 |
| PERMIT_DATE | 0 | 0 | 118 → 118 |
| FINAL_DATE | 1,040 | 0 | 2,000 → 960 |

Coverage after repair: FILE_DATE 35.0% all statuses; Active/Final PERMIT_DATE 1,696/1,720 (98.6%); Final FINAL_DATE 1,040/1,245 (83.5%). Missing FILE_DATE increased because incorrect Issue-Date / checklist copies were cleared.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_wakulla_county.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_wakulla_county_repaired.parquet`
