# Williams (CA) data repair

**Summary:** Williams was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script (1,082 rows; La Cañada Flintridge already maps to `data_repair_ca_la_canada_flintridge.py`). DATA is a flat civic portal payload (`Status` + `Permit Date` + inspections). Upstream status mappings match `DATA.Status` wherever Status is nonempty; the main gaps are 100% missing PERMIT_DATE / FINAL_DATE and 71 blank-Status nulls. Repair promotes 2 Open shells with passed final inspections to Final and fills 123 FINAL_DATE values from passed final inspections (type or notes). FILE_DATE was already complete. No Issued Date exists, so PERMIT_DATE stays empty for all rows.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Williams, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Flat civic portal scrape. Core keys: `Status`, `Permit Date`, `Permit Number`, `Applicant Name`, `Description of Work`, `Square Feet`, `permit_id`, `fees`, `payments`, `contractors`, `inspections`, `property_info`. Optional `reviews` / `plan_reviews` / `record_type_from_contractor_box` distinguish variants. There is no `Issued Date`, `Issue Date`, or `Finalized Date`.

| Schema | n |
| --- | ---: |
| `portal_reviews` | 1,018 |
| `portal_plan_reviews_rtype` | 45 |
| `portal_plan_reviews` | 19 |

Canonical fields: `Status` → STATUS_NORMALIZED; `Permit Date` → FILE_DATE (application/submittal); passed final inspection `completed_date` (type or notes contain "final") → FINAL_DATE.

Portal Status labels (sample): Final 568, Open 242, Pending 91, Closed 89, blank 71, Expired 17, Quote 4.

## Field assessment

### STATUS_NORMALIZED

Before: Final 657 / In Review 337 / Inactive 17 / missing 71. No Active rows.

Where `DATA.Status` is nonempty, upstream STATUS_NORMALIZED already matched the intended map exactly (Final/Closed → Final; Open/Pending/Quote → In Review; Expired → Inactive). No wrong non-null values.

Gaps and overrides:

- **Blank Status (71):** STATUS_ORIGINAL null; no inspections; a handful have payments only → left null (cannot reliably classify).
- **Open + passed final inspection (2):** portal lag; FIXED In Review → Final.

After: Final 659 / In Review 335 / Inactive 17 / missing 71.

### FILE_DATE

Fully populated. Calendar-day match to `Permit Date` for all 1,082 rows. No fills/fixes. Coverage: 100%.

### PERMIT_DATE

Missing on every row. The portal field named `Permit Date` is the application/submittal date (already used as FILE_DATE), not issuance. No `Issued Date` / `Issue Date` exists. Payment `date` values are fee receipts (often days after file date) and are not treated as issuance. Active/Final PERMIT_DATE therefore remains empty (0 / 659 Final).

### FINAL_DATE

Missing on every row before repair. No `Finalized Date` field. Fillable evidence is limited to inspections:

- Passed inspection whose `inspection_type` contains "final" (e.g. `B - Final Inspection`, `Pool - Final`), or
- Passed inspection whose notes mention "final" (common for solar/stucco recorded as `B - Electrical` / `B - Other`).

Filled 123 Final rows (120 already-Final, 1 Closed, 2 promoted Open). Remaining Final rows (~536) have empty or non-final inspections → FINAL_DATE stays missing. No chronology inversions (FINAL_DATE < FILE_DATE) among filled rows.

After repair: Final FINAL_DATE 123 / 659 (18.7%); absent on all non-Final.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_williams.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_williams_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 2 | 71 → 71 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 1,082 → 1,082 |
| FINAL_DATE | 123 | 0 | 1,082 → 959 |

After repair:

- FILE_DATE: 1,082 / 1,082 (100%)
- Active PERMIT_DATE: n/a (0 Active)
- Final PERMIT_DATE: 0% (no issuance field in DATA)
- Final FINAL_DATE: 18.7%
- Blank-Status STATUS_NORMALIZED gaps unchanged (71)
