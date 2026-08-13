# Fort Myers Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (ordered `(JURISDICTION, STATE)`) was **Fort Myers Beach**. DATA is a flat city-portal payload (`Status`, `Permit Date`, `Issued Date`, `Finaled Date`, `inspections`, …). Upstream left 84 `STATUS_NORMALIZED` nulls (mostly waiting-on-docs/resubmittal), mislabeled 6 unissued review rows as Active via stale `STATUS_ORIGINAL=issued`, and kept 3 ISSUED rows as Active despite a populated `Finaled Date`. `FILE_DATE` already matched portal **Permit Date** (application stamp) for every row. Spurious `PERMIT_DATE` values on unissued rows came from Permit Date / review timestamps rather than **Issued Date**; those were cleared and Active/Final issuance aligned to Issued Date. `FINAL_DATE` gaps on Final were filled from Finaled Date or passed Final/CO inspections; non-Final final stamps were cleared. After repair: STATUS 99.5%; FILE_DATE 100%; Active/Final PERMIT_DATE 98.3%/80.2%; Final FINAL_DATE 90.7%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Fort Myers Beach, FL** → `agent/scripts/fl/data_repair_fl_fort_myers_beach.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level portal shape; schemas are labeled `city_portal_{status_slug}_{content}` by Status and which canonical dates are populated:

| Schema (top) | n | Notes |
| --- | ---: | --- |
| `city_portal_finaled_issued_finaled` | 813 | Finaled + Issued + Finaled Date |
| `city_portal_issued_issued` | 403 | Issued, no Finaled Date |
| `city_portal_finaled_finaled` | 148 | Finaled Date, blank Issued Date |
| `city_portal_void_applied` | 98 | Void, application only |
| `city_portal_in_review_applied` | 90 | In review, application only |
| `city_portal_*_applied` / others | 548 | Waiting / abandoned / closed / blank / … |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status`, with Finaled Date / Issued Date overrides (inactive Status wins) |
| FILE_DATE | `Permit Date` (application / submittal — not issuance) |
| PERMIT_DATE | `Issued Date` |
| FINAL_DATE | `Finaled Date`, else latest passed Final/CO `inspections` date |

## Field assessments

### STATUS_NORMALIZED

Upstream mapped mostly from `STATUS_ORIGINAL` / `Status`:

| Status | Upstream | Assessment |
| --- | --- | --- |
| FINALED / CLOSED | Final | Correct |
| ISSUED / APPROVED | Active | Correct unless Finaled Date present → Final |
| IN REVIEW / WAITING FOR PAYMENT / … | In Review (partial) | Waiting-on-docs / resubmittal / fire fees often **null** |
| VOID / ABANDONED / EXPIRED / DENIED / … | Inactive | Correct |
| *(blank)* | null (10) | Not repairable |

**Root causes:**
1. Waiting statuses (`WAITING ON RESUBMITTAL`, `WAITING FOR REQUIRED DOC`, `FIRE FEES TO BE PAID`) were not mapped → 74 nulls filled as In Review (plus 3 null→Active via Issued Date).
2. Stale `STATUS_ORIGINAL=issued` kept 6 unissued IN REVIEW / WAITING rows as Active → FIXED to In Review.
3. Three ISSUED rows already had `Finaled Date` → FIXED to Final; one ISSUED row labeled Final via stale `STATUS_ORIGINAL=finaled` (no Finaled Date) → FIXED to Active.
4. Six review-labeled rows that already carry Issued Date → FIXED to Active (issuance override).

**Repair performance:** FILLED 74, FIXED 16; missing 84 → 10 (blank Status shells).

### FILE_DATE

- Before: missing on **0 / 2,000**. All values matched portal `Permit Date` at calendar-day resolution.
- In this portal, `Permit Date` is the application/submittal stamp (often before `Issued Date`); it is the correct FILE_DATE source.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: NaN on **393 / 2,000**. Present values usually matched `Issued Date`, but 68 equaled `Permit Date` only (unissued) and ~129 matched review timestamps rather than issuance.
- Ideal PERMIT_DATE is issuance → **Issued Date**. In Review must not carry PERMIT_DATE.

**Repair performance:** FILLED 1, FIXED 197 (mostly clears of spurious stamps + Issued Date alignment). Missing 393 → 589. Active 98.3% (7 ISSUED/APPROVED shells lack Issued Date); Final 80.2% (215 Finals lack Issued Date, including many CLOSED/FINALED application-only shells); In Review 0%.

### FINAL_DATE

- Before: NaN on **1,018 / 2,000**; Final coverage 975 / 1,084 (89.9%). Present Final values already matched `Finaled Date`. Seven non-Final rows carried Finaled Date stamps (3 ISSUED Active, 4 Inactive).
- Repair: Final ← Finaled Date, else passed Final/CO inspection; clear FINAL_DATE on non-Final.

**Repair performance:** FILLED 8, FIXED 5; missing 1,018 → 1,015. Final coverage 985 / 1,086 (90.7%). Remaining ~101 Final gaps lack Finaled Date and a dated Final/CO pass. Non-Final rows correctly have 0% FINAL_DATE. PERMIT_DATE > FINAL_DATE inversions: 4 (portal `Finaled Date` before `Issued Date` — left as-is).

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_fort_myers_beach.py`
- Repaired sample: `$AGENT_DATA_PATH/fort_myers_beach_repaired_sample.parquet`
