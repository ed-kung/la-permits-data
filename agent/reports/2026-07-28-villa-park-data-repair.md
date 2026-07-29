# Villa Park (CA) data repair

**Summary:** For the first sample jurisdiction lacking a repair script (Villa Park, CA; 2,000 rows), upstream left **852** `STATUS_NORMALIZED` null because portal statuses such as Paid and Issued / Approved Plan Check were never mapped; repair filled **805** and fixed **3** (including Issued→Final promotions when `Finalized Date` is present). `FILE_DATE` already matched `Permit Date` everywhere. All **14** existing `PERMIT_DATE` values were plan-review completion stamps, not issuance, and were cleared; no Issued Date exists in DATA so Active/Final issuance coverage stays 0%. `FINAL_DATE` was cleared on **26** non-Final / sentinel rows; Final coverage is **445 / 573 (77.7%)**.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Villa Park, CA** (`data_repair_ca_villa_park.py`).

## DATA schemas (`INFERRED_SCHEMA`)

Flat civic portal scrape. Core keys: `Status`, `Permit Date`, `Finalized Date`, `Permit Number`, `Permit Type`, plus nested `fees` / `payments` / `inspections` / `property_info`. Optional `reviews` / `plan_reviews` / `record_type_from_contractor_box` distinguish variants.

| Schema | n |
| --- | ---: |
| `portal_reviews` | 1,885 |
| `portal_plan_reviews_rtype` | 90 |
| `portal_plan_reviews` | 25 |

Canonical fields: `Status`; `Permit Date` (application, not issuance); `Finalized Date` (ignore `01/01/1900`).

## Field assessment

### STATUS_NORMALIZED

Before: Active 168 / Final 558 / In Review 270 / Inactive 152 / missing 852.

Upstream mapped only a subset of portal `Status` values. Unmapped (and null) in the sample:

| DATA.Status | n | Repair target |
| --- | ---: | --- |
| Paid and Issued | 681 | Active (or Final if `Finalized Date` present) |
| Approved Plan Check | 80 | In Review |
| (blank) | 46 | left null |
| Approved Pending Payment | 33 | In Review |
| Submitted Pending Payment | 10 | In Review |
| Engineering General | 1 | left null |

Additionally, Active rows with a real `Finalized Date` are promoted to Final (portal status lag): **13** Paid and Issued and **2** Issued. One row had `STATUS_ORIGINAL`/`STATUS_NORMALIZED` lagging behind DATA.Status=Paid and Issued (In Review → Active).

After: Active 836 / Final 573 / In Review 392 / Inactive 152 / missing 47.

### FILE_DATE

Fully populated. Every value equals DATA `Permit Date` at calendar-day resolution. No FILLED/FIXED. Coverage remains 2,000 / 2,000.

### PERMIT_DATE

Missing on 1,986 / 2,000. The 14 populated values all match `plan_reviews[].completed_date` or `reviews[].completed_date` — plan-check stamps, not issuance. Villa Park DATA has no `Issued Date` / `Issue Date` field, and `Permit Date` is the application date (already used as `FILE_DATE`). Those 14 values were cleared (FIXED). Active/Final issuance coverage after repair: **0%**.

### FINAL_DATE

`Finalized Date` is the true finaling stamp when present and not the `01/01/1900` sentinel (22 Opened/Void rows). Before repair, 41 non-Final rows carried `FINAL_DATE` (sentinels + leftovers on Issued / Paid and Issued / void / expired / approved plan check). After promoting 15 Active→Final (which already matched `Finalized Date`), **26** remaining non-Final / sentinel values were cleared. Finaled rows with empty `Finalized Date` (**128**) cannot be filled — inspections often say "Final" but lack `completed_date`.

After repair: Final 445 / 573 (77.7%); cleared on all non-Final.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_villa_park.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_villa_park_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 805 | 3 | 852 → 47 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 14 | 1,986 → 2,000 |
| FINAL_DATE | 0 | 26 | 1,529 → 1,555 |

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 0%; Final 0% (no issuance field in DATA)
- FINAL_DATE: Final 77.7%; absent on non-Final
