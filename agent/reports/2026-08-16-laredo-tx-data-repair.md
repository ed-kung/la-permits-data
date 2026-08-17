# Laredo (TX) data repair

**Summary:** Laredo was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,001 rows). DATA is a municipal portal payload (`full_portal` / `detail_only`), same family as Killeen. STATUS_NORMALIZED is now fully populated (78 FILLED from early-review / cancelled detail-only shells). FILE_DATE was already correct (100%). PERMIT_DATE was systematically wrong whenever `Permit Date` diverged from `Issue Date` — the pipeline had used `Permit Date`, which for Active rows often equals the application day and for Final rows is often a later completion stamp — 498 FIXED to `Issue Date`. FINAL_DATE gained 3 fixes (one rough-in mis-match; two fire-insp rows aligned to Permit Date). After repair: Active/Final PERMIT_DATE 100%; Final FINAL_DATE 100%; STATUS missing 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Killeen (plus several later cities already present). **Laredo** was the first missing pair → `agent/scripts/tx/data_repair_tx_laredo.py`.

## DATA schema

All 2,001 rows parse. Shared top-level keys: `fees`, `detail`, `fees_total`; 1,923 also have `insp_status`, `permit_status`, `insp_status_detail`, `permit_status_detail`.

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `full_portal` | 1,923 | `detail` + `permit_status_detail` populated |
| `detail_only` | 78 | No permit_status block; early Application Status only |

Canonical sources:

| Target | Primary | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number` | `detail.Application Status` (detail_only) |
| FILE_DATE | `detail.Application Date` | `permit_status_detail.Application Date` |
| PERMIT_DATE | `Issue Date` | `Permit Date` when Issue blank |
| FINAL_DATE | approved BUILDING FINAL / FINAL insp | other approved `*FINAL*` (excl. TEMPORARY); then `Permit Date` (Final only) |

## Field assessment

### STATUS_NORMALIZED

Before: Active 1,338 / In Review 465 / Final 115 / Inactive 5 / missing 78.

Mapping from `Status for Permit Number` was already correct on all `full_portal` rows:

| Status for Permit Number | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| PERMIT PRINTED | Active | 1,338 |
| TO BE ISSUED | In Review | 380 |
| C.O. ISSUED | Final | 95 |
| PLAN CHECK | In Review | 85 |
| FINAL INSPECTION COMPLETE | Final | 20 |
| PERMIT REVOKED | Inactive | 5 |

**Missing (78) — FILLED** from `Application Status` on `detail_only` rows (no permit_status block, so prior pipeline left STATUS null):

| Application Status | → | n |
| --- | --- | ---: |
| REVIEWED FOR CODE COMP | In Review | 67 |
| PR - IN PLAN REVIEW | In Review | 5 |
| APPLICATION PRESCREEN | In Review | 4 |
| CANCELLED ADMINISTRATIVE | Inactive | 2 |

Root cause: early-review / cancelled applications never received a permit_status payload; only `detail` was scraped.

Application Status often disagrees with permit status (e.g. CERTIFICATE OF OCCUPANCY / EXPIRED / PERMIT ISSUED while Status remains PERMIT PRINTED or TO BE ISSUED). Permit status is treated as authoritative (matches STATUS_ORIGINAL); those rows were not reclassified.

After repair: Active 1,338 / In Review 541 / Final 115 / Inactive 7 / missing 0.

### FILE_DATE

- Present on all 2,001 rows; every value matches `detail.Application Date` at day resolution.
- `detail` and `permit_status_detail` Application Dates never diverge in this sample.
- No FILLED / FIXED.

### PERMIT_DATE

- Prior values always equaled `Permit Date` when that field existed (1,923 rows).
- `Issue Date` and `Permit Date` are equal on 1,313 rows, but **differ on 498**.
  - **Active (335):** Permit Date is typically one calendar day before Issue Date and often equals Application Date — not a true issuance stamp.
  - **Final (113):** Permit Date is typically much later than Issue (median +84 days) and behaves like a completion / final stamp.
  - **In Review (49) / Inactive (1):** same Issue-vs-Permit divergence when Issue is present.
- Prior pipeline therefore set PERMIT_DATE to application-like or finaling-like dates instead of issuance.
- **498 FIXED** to `Issue Date`: Active 335 / Final 113 / In Review 49 / Inactive 1.
- After repair, every row with a non-blank Issue Date has PERMIT_DATE == Issue Date (1,811 / 1,811).
- 78 detail_only rows remain without PERMIT_DATE (76 In Review / 2 Inactive; no Issue or Permit Date in DATA). Active and Final coverage is 100%.

### FINAL_DATE

- Before: present on all 115 Final rows; absent on all non-Final (correct).
- When present, most matched an approved trade `*FINAL*` inspection (esp. ML FINAL); a minority matched `Permit Date` and/or non-final inspections.
- One C.O. ISSUED row had FINAL_DATE equal to an approved **ML ROUGH-IN** (07/07/17) while an earlier **ML FINAL** (07/05/17) existed → FIXED to ML FINAL.
- Two FINAL INSPECTION COMPLETE rows had only fire inspections (no name containing FINAL) → FIXED to `Permit Date` (1-day shift).

Repairs:

| Action | n | Notes |
| --- | ---: | --- |
| FIXED | 3 | 1 rough-in → ML FINAL; 2 fire-insp → Permit Date |
| FILLED | 0 | already present on all Final |

After repair: Final FINAL_DATE 100%; non-Final remain empty. Final rows with PERMIT_DATE == FINAL_DATE dropped to 1 (was 10 before, because PERMIT_DATE no longer uses the completion-like Permit Date).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 78 | 0 | 78 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 498 | 78 → 78 |
| FINAL_DATE | 0 | 3 | 1,886 → 1,886 |

Ideal coverage after repair:

- FILE_DATE populated: 2,001 / 2,001 (100%)
- PERMIT_DATE for Active/Final: 1,453 / 1,453 (100%)
- FINAL_DATE for Final: 115 / 115 (100%)

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_laredo.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_laredo_repaired.parquet`
