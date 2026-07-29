# West Sacramento (CA) data repair — 2026-07-28

West Sacramento was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON already has complete `FILE_DATE` (from `DATA.date`) and mostly correct `STATUS_NORMALIZED` from `DATA.status`, but 66 `Estimate` shells were labeled Final, `PERMIT_DATE` was often the Processing / Ready-to-Issue stamp rather than Issued, and `FINAL_DATE` was systematically set to the Issued date instead of Finaled / Final Approved. Repair fixes 70 statuses, 12 file dates, 893 permit dates (500 fill + 393 fix), and 1,115 final dates (64 fill + 1,051 fix), and clears 1 spurious final date on a non-Final row.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **West Sacramento, CA** → `agent/scripts/ca/data_repair_ca_west_sacramento.py` (n=2,000).

## DATA schema

Accela Citizen Access scrape. All rows share top-level keys (`address`, `date`, `status`, `tasks`, `search_data`, `details`, …); 4 rows omit `inspections` / `conditions` / `fees_details`. Workflow events use `Marked as <status> on <date>` (HTML spans), not Menlo Park’s `Completed on … as …` form. Variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_issued_finaled` | 1,061 | Issued + final-date evidence |
| `portal_application_only` | 607 | application / top-level date only |
| `portal_issued` | 270 | Issued present, no final date |
| `portal_final_only` | 62 | final date present, no Issued |

## Field assessment

### STATUS_NORMALIZED

- Fully populated (0 missing). Upstream mapped `STATUS_ORIGINAL` / `DATA.status` into the four buckets for most labels (`Finaled` / `Closed` / `Complete` → Final; `Issued` / `Active` / `Enforcement` → Active; `In Review` / `Applied` / `Ready to Issue` → In Review; `Expired*` / `Withdrawn` / `Canceled` → Inactive).
- **Incorrect vs DATA:**
  - `Estimate` (66) labeled Final despite empty Issued / Finaled workflow → FIXED to In Review.
  - `Temp C of O Issued` (1) labeled Final → FIXED to Active (temporary CO, not finaled).
  - `Revision Pending` (3) with dated Issued* still In Review → FIXED to Active (status lag).
- **Repair:** 0 FILLED, 70 FIXED. Missing after: 0.

### FILE_DATE

- Fully populated; every value matched `DATA.date` before repair.
- 12 rows had an earlier Application Submittal / Distribution first-touch mark than the (re-opened) top-level date → FIXED to the earlier date.
- **Repair:** 0 FILLED, 12 FIXED. Coverage 2,000 / 2,000 (100%).

### PERMIT_DATE

- Upstream often used Processing `Ready to Issue` or Building `Approved` instead of Ready to Issue / Application Submittal `Issued`.
- Fillable: 500 Active / Final / post-issue Inactive rows with Issued* marks and blank `PERMIT_DATE` → FILLED.
- Incorrect: 393 rows whose stamp did not match Issued* → FIXED to the Issued date.
- Unfillable after repair: 54 Active (`active` / `enforcement` / `inspections` with no Issued mark) and 285 Final (`finaled` 228 / `closed` 36 / `complete` 21) lack Issued evidence in tasks.
- In Review: 0% by design (spurious pre-issue stamps cleared when no Issued*).
- **Repair:** 500 FILLED, 393 FIXED. Missing after: 669.
- Post-repair Active+Final PERMIT coverage: 1,210 / 1,549 (78.1%).

### FINAL_DATE

- Systematically wrong before repair: when present on Final rows, `FINAL_DATE` almost always matched Issued / Ready-to-Issue rather than Finaled / Final Approved (only ~2 calendar-day matches to true final marks).
- Canonical source order: any `Finaled` → `C of O Issued` → Final Processing `Final Approved` → any `Final Approved` → Closed task `Closed`/`Close` → final-titled inspection Status Date.
- Fillable: 64 Final rows with blank `FINAL_DATE` but final evidence → FILLED.
- Incorrect: 1,051 Final rows with Issued-as-final stamps → FIXED.
- Spurious: 1 Active (`Issued`) row carrying a final stamp → cleared (FIXED).
- Unfillable: 224 Final (`finaled` 209 / `closed` 15); only 8 of those have any dated task events (rest are TBD/empty histories).
- **Repair:** 64 FILLED, 1,051 FIXED (includes 1 clear). Missing after: 884.
- Post-repair Final FINAL coverage: 1,116 / 1,340 (83.3%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 70 | 0 | 0 |
| FILE_DATE | 0 | 12 | 0 | 0 |
| PERMIT_DATE | 500 | 393 | 1,169 | 669 |
| FINAL_DATE | 64 | 1,051 | 947 | 884 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,407 | 1,340 |
| Inactive | 231 | 231 |
| Active | 205 | 209 |
| In Review | 157 | 220 |

Status transitions (FIXED): Final→In Review 66; In Review→Active 3; Final→Active 1.

Chronology after repair: `PERMIT < FILE` = 0; `FINAL < PERMIT` = 0.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_west_sacramento.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_west_sacramento_repaired.parquet`
