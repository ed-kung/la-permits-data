# Hillsborough County (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Hillsborough County was first. Its DATA is Accela Civic Access JSON (same family as Tampa). STATUS_NORMALIZED had 9 gaps and 28 stale/wrong labels (notably About to Expire→Inactive and In Review after Issuance). FILE_DATE already matched `DATA.date` on all 2,000 rows. PERMIT_DATE needed 6 fixes to Issuance Issued*; 382 gaps remain where DATA has no issuance event. FINAL_DATE gained 170 fills and 38 value corrections from final inspections / Inspection Complete / Closure, with 1 spurious non-Final value cleared; 11 Final rows still lack any completion stamp in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Hillsborough County, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_hillsborough_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/hillsborough_county_repaired_sample.parquet`

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `accela_with_inspections` | 1,025 | non-empty `inspections` plus workflow `tasks` |
| `accela_no_inspections` | 975 | tasks / detail only |

All rows share the same top-level keys (`status`, `date`, `tasks`, `inspections`, `search_data`, …).

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status`, with Closure Complete→Final and Issuance Issued*→Active overrides when the portal label lags |
| FILE_DATE | `DATA.date` (fallback `search_data.Date`) |
| PERMIT_DATE | Earliest Issuance Marked as Issued / Issued with Conditions / Revision Issued |
| FINAL_DATE | Latest APPROVED inspection with "final" in title; else first Inspection Complete; else Closure Complete/Closed/Revision Complete; else Certification COC/COO Issued; else latest APPROVED inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 968, Active 687, In Review 175, Inactive 161, missing 9.

**9 FILLED** from previously unmapped portal statuses:

| After | DATA.status / STATUS_ORIGINAL | n |
| --- | --- | ---: |
| In Review | empty + Awaiting Plans | 3 |
| In Review | I-ASSIGN / INPROCESS | 2 |
| Inactive | E-NOCMP (Velocity Hall code) | 4 |

**28 FIXED:**

| Before → After | Reason | n |
| --- | --- | ---: |
| Inactive → Active | About to Expire is still a valid issued permit | 8 |
| In Review → Active | Issuance Issued* present; portal status lagged | 18 |
| In Review → Final | Closure Complete present | 1 |
| Active → Final | Closure Complete present on Issued row | 1 |

After repair: Final 970, Active 712, In Review 161, Inactive 157. **0 missing.**

### FILE_DATE

Ideal: populated for all records. Every FILE_DATE already equals top-level `DATA.date` at day resolution. **0 FILLED / 0 FIXED.** Coverage after repair: 100% for all statuses.

### PERMIT_DATE

Ideal: populated for Active and Final.

- **6 FIXED** to earliest Issuance Issued* (including cases where upstream used a non-issuance date, or lagged behind Issued with Conditions → later Issued).
- **0 FILLED** — every missing Active/Final row lacks an Issuance Issued* event in DATA (11 legacy `ISSUED` / 4 About to Expire without task history; 106 Complete/Closed without Issuance Issued*).
- After status overrides, no In Review rows retain a PERMIT_DATE (issuance-backed rows moved to Active).

Coverage after repair: Active 697/712 (97.9%); Final 864/970 (89.1%); In Review 0/161; Inactive 57/157. Where an Issuance Issued* date exists, PERMIT_DATE matches it on **1,617/1,617** rows.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 788 Final + 1 In Review + 1 Inactive had FINAL_DATE; 180 Final were missing.
- **170 FILLED** from final inspections / Inspection Complete / Closure (and related) for Complete rows that already carried completion evidence in DATA.
- **38 FIXED** to the canonical candidate (usually a final-titled APPROVED inspection preferred over an earlier Inspection-Complete / Closure stamp).
- **1 FIXED clear** of a spurious FINAL_DATE on a non-Final row.
- **11 Final still missing** — Admin Payments, Velocity Hall Status-only, permit extension, and similar records with no inspections / Inspection-Complete / Closure-Complete / Certification events.

Coverage after repair: Final 959/970 (98.9%); Active / In Review / Inactive 0%. No PERMIT_DATE > FINAL_DATE chronology violations.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 9 | 28 | 9 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 6 | 382 → 382 |
| FINAL_DATE | 170 | 39 | 1,210 → 1,041 |

Main corrective actions are (1) remapping stale About to Expire / post-issuance In Review labels, (2) aligning PERMIT_DATE to Issuance Issued*, and (3) filling Final completion dates from Accela inspections and workflow tasks. Issuance and completion stamps remain unavailable for a minority of legacy Velocity Hall / admin records that never recorded those events in DATA.
