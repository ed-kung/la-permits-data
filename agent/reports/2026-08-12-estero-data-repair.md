# Estero (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Estero**. DATA is a city-portal payload (`Applications` / `Permit Information` / `Inspections History`) with two key-casing variants (`city_portal_pascal`, `city_portal_lower`). Upstream left all 530 lowercase-schema rows with null `STATUS_NORMALIZED` (mostly `Permit Closed` → Final and `Permit Issued` → Active). `FILE_DATE` already matched earliest `AppDate`/`appdate` except 4 empty-Application shells. `PERMIT_DATE` was a `FILE_DATE` copy on issued pascal rows and missing on lowercase rows; only 44 rows have a real `ApprovedByDate`. `FINAL_DATE` was universally null and is now filled from Pass/Passed FINAL inspections for 98.3% of Final rows. After repair: STATUS fully populated; FILE_DATE 99.8%; Active/Final PERMIT_DATE 68.6%; Final FINAL_DATE 98.3%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py` (slug via `[^a-z0-9]+` → `_`). First missing: **Estero, FL** → `agent/scripts/fl/data_repair_fl_estero.py` (2,002 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `city_portal_pascal` | 1,436 | `StatusDesc` / `AppDate` / `ApprovedByDate`; Permit Information usually a one-element list |
| `city_portal_lower` | 566 | `statusdesc` / `appdate`; Permit Information often a bare dict |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Permit Information` `StatusDesc` / `statusdesc` (whitespace-stripped) |
| FILE_DATE | earliest `Applications[].AppDate` / `appdate` |
| PERMIT_DATE | earliest `Applications[].ApprovedByDate` / `approvedbydate` when present |
| FINAL_DATE | latest Pass/Passed inspection with `"FINAL"` in `inspectiondesc` (`scheduleddate`) |

## Field assessments

### STATUS_NORMALIZED

| StatusDesc | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Permit Complete | 1,087 | Final | Correct |
| Permit Closed | 480 | Final (35) / **null (445)** | Lowercase schema unmapped |
| Permit Issued | 190 | Active (118) / **null (72)** | Lowercase schema unmapped |
| Voided | 120 | Inactive (119) / **null (1)** | Near-complete; strip `\r\n` |
| Expired | 59 | Inactive (51) / **null (8)** | Lowercase unmapped |
| Canceled Permit | 29 | Inactive (25) / **null (4)** | Lowercase unmapped |
| Plan Review | 21 | In Review | Correct |
| Application | 14 | In Review | Correct |
| Incomplete | 2 | In Review | Correct |

**Root cause of nulls:** the upstream normalizer only consumed pascal-case `STATUS_ORIGINAL` / `StatusDesc`. The lowercase extract (`statusdesc`, often with `Permit Closed`) left `STATUS_ORIGINAL` and `STATUS_NORMALIZED` null on all 530 `city_portal_lower` rows.

**Repair performance:** FILLED 530, FIXED 0; missing 530 → 0.

Fills: Permit Closed→Final 445; Permit Issued→Active 72; Expired/Canceled/Voided→Inactive 13.

### FILE_DATE

- Before: missing on **4 / 2,002** rows (Inactive shells with empty `Applications` and no other dates).
- Earliest `AppDate`/`appdate` matches existing `FILE_DATE` on every row that has applications (0 calendar-day mismatches).
- After: still 4 missing; no fills or fixes.
- Active / Final / In Review coverage: **100%**.

**Repair performance:** FILLED 0, FIXED 0; missing 4 → 4.

### PERMIT_DATE

- Before: missing on **570** rows (all lowercase-schema rows plus none of the pascal Active/Final set).
- Pascal Active/Final: `PERMIT_DATE` equals `FILE_DATE` on every row (upstream copy). Real `ApprovedByDate` exists on only **44** rows and differs from that copy on **37** → overwritten (FIXED).
- In Review: all **37** had a spurious `PERMIT_DATE == FILE_DATE` → cleared (FIXED).
- Lowercase Active/Final (72 + 480): no `approvedbydate` in DATA → remain missing (no reliable issuance timestamp; plan-review / fee / first-inspection dates are not treated as permit issue dates).

**Repair performance:** FILLED 0, FIXED 69 (32 ApprovedByDate overwrites + 37 In Review clears); missing 570 → 607.

Active/Final coverage after repair: **1,205 / 1,757 (68.6%)**. Remaining gaps are entirely `city_portal_lower`.

### FINAL_DATE

- Before: missing on **all 2,002** rows, including every Final record.
- Source: latest inspection with `statusdesc` in `{Pass, Passed}` and `"FINAL"` in `inspectiondesc`.
- After: filled on **1,540 / 1,567** Final rows (98.3%). The 27 gaps have empty inspection history or no Pass/Passed FINAL inspection.
- No FINAL_DATE left on non-Final statuses; no PERMIT > FINAL inversions.

**Repair performance:** FILLED 1,540, FIXED 0; missing 2,002 → 462.

## Ideal-field checklist (after repair)

| Rule | Result |
| --- | --- |
| FILE_DATE populated for all records | Nearly (99.8%; 4 Inactive shells) |
| PERMIT_DATE for Active and Final | Partial (68.6% — no issuance date in lowercase extract) |
| FINAL_DATE for Final | Yes (98.3%) |

Status distribution after repair: Final 1,567; Inactive 208; Active 190; In Review 37.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_estero.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/estero_repaired_sample.parquet`
