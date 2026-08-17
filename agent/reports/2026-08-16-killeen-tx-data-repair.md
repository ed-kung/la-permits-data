# Killeen (TX) data repair

**Summary:** Killeen was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows). DATA is a municipal portal payload (`full_portal` / `detail_only`). STATUS_NORMALIZED is now fully populated (15 FILLED from REJECTED / PLAN REVIEW detail-only shells). FILE_DATE was already correct (100%). PERMIT_DATE was systematically wrong whenever `Permit Date` diverged from `Issue Date` — the pipeline had used `Permit Date`, which for completed permits often stores the completion stamp — 586 FIXED to `Issue Date`. FINAL_DATE gained 2 fills and 77 fixes (mostly C.O. ISSUED rows whose FINAL_DATE matched an intermediate inspection). After repair: Active/Final PERMIT_DATE 100%; Final FINAL_DATE 100%; STATUS missing 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Flower Mound (plus Arlington / Baytown / Allen / Bellaire further down the list). **Killeen** was the first missing pair → `agent/scripts/tx/data_repair_tx_killeen.py`.

## DATA schema

All 2,000 rows parse. Shared top-level keys: `fees`, `detail`, `fees_total`; nearly all also have `insp_status`, `permit_status`, `insp_status_detail`, `permit_status_detail`.

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `full_portal` | 1,985 | `detail` + `permit_status_detail` populated |
| `detail_only` | 15 | No permit_status block; Application Status REJECTED (14) or PLAN REVIEW (1) |

Canonical sources:

| Target | Primary | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number` | `detail.Application Status` (detail_only) |
| FILE_DATE | `detail.Application Date` | `permit_status_detail.Application Date` |
| PERMIT_DATE | `Issue Date` | `Permit Date` when Issue blank |
| FINAL_DATE | approved BUILDING FINAL / FINAL insp | other approved `*FINAL*` (excl. TEMPORARY); then `Permit Date` (Final only) |

## Field assessment

### STATUS_NORMALIZED

Before: Active 1,383 / Final 534 / Inactive 53 / In Review 15 / missing 15.

Mapping from `Status for Permit Number` was already correct on all `full_portal` rows:

| Status for Permit Number | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| PERMIT PRINTED | Active | 1,383 |
| FINAL INSPECTION COMPLETE | Final | 437 |
| C.O. ISSUED | Final | 95 |
| CLOSED | Final | 2 |
| TO BE ISSUED | In Review | 13 |
| PLAN CHECK | In Review | 2 |
| PERMIT REVOKED | Inactive | 53 |

**Missing (15) — FILLED** from `Application Status` on `detail_only` rows (no permit_status block, so prior pipeline left STATUS null):

| Application Status | → | n |
| --- | --- | ---: |
| REJECTED | Inactive | 14 |
| PLAN REVIEW | In Review | 1 |

Root cause: rejected / early plan-review applications never received a permit_status payload; only `detail` was scraped.

Application Status sometimes disagrees with permit status (e.g. CLOSED / EXPIRED / ON HOLD while Status remains PERMIT PRINTED). Permit status is treated as authoritative (matches STATUS_ORIGINAL); those rows were not reclassified.

After repair: Active 1,383 / Final 534 / Inactive 67 / In Review 16 / missing 0.

### FILE_DATE

- Present on all 2,000 rows; every value matches `detail.Application Date` at day resolution.
- `detail` and `permit_status_detail` Application Dates never diverge in this sample.
- No FILLED / FIXED.

### PERMIT_DATE

- Prior values always equaled `Permit Date` when that field existed (1,985 rows).
- `Issue Date` and `Permit Date` are equal on 1,342 rows, but **differ on 586**. For Final rows especially (509 / 534), `Permit Date` is often the completion / final stamp (matches BUILDING FINAL on 373 Final rows) while `Issue Date` retains issuance.
- Prior pipeline therefore set PERMIT_DATE to a finaling-like date for most Final records (439 Final rows had PERMIT_DATE == FINAL_DATE).
- **586 FIXED** to `Issue Date`: Final 509 / Active 69 / Inactive 8.
- 15 detail_only rows remain without PERMIT_DATE (Inactive / In Review; no Issue or Permit Date in DATA). Active and Final coverage is 100%.

### FINAL_DATE

- Before: present on 532 / 534 Final rows; absent on all non-Final (correct).
- When present, 390 matched an approved BUILDING FINAL / FINAL inspection; 66 matched `Permit Date` only; **75 matched an intermediate inspection** (TEMP POLE, insulation, rough-in) — common on C.O. ISSUED rows whose insp list never recorded a building final.
- Two CLOSED Final rows had no FINAL_DATE and empty inspections → fillable from `Permit Date` (≠ Issue Date).

Repairs:

| Action | n | Source |
| --- | ---: | --- |
| FILLED | 2 | `Permit Date` (CLOSED) |
| FIXED | 76 | `Permit Date` (mostly C.O. ISSUED with junk intermediate-insp dates) |
| FIXED | 1 | approved final inspection |

After repair: Final FINAL_DATE 534 / 534 (100%); sources 390 insp + 144 Permit Date only. Non-Final FINAL_DATE remains empty. Final rows with PERMIT_DATE == FINAL_DATE dropped from 439 → 25 (same-day issue and completion).

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_killeen.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_tx_killeen_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 15 | 0 | 15 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 586 | 15 → 15 |
| FINAL_DATE | 2 | 77 | 1,468 → 1,466 |

Post-repair coverage:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 1,383 / 1,383 (100%) | 0 / 1,383 |
| Final | 534 / 534 (100%) | 534 / 534 (100%) |
| In Review | 15 / 16 | 0 / 16 |
| Inactive | 53 / 67 | 0 / 67 |

## Remaining gaps

- 15 detail_only REJECTED / PLAN REVIEW rows have no issuance or completion dates in DATA (expected; not Active/Final).
- 14 Inactive rows (mostly revoked without Issue Date) keep PERMIT_DATE from `Permit Date` only; 14 newly filled Inactive REJECTED rows have no PERMIT_DATE.
- Active PERMIT PRINTED rows that already show an approved BUILDING FINAL are left Active per portal status; FINAL_DATE is not populated for non-Final.
