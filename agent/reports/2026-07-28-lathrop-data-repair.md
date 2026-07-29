# Lathrop (CA) data repair

**Summary:** Lathrop was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script (La Cañada Flintridge already covered by `data_repair_ca_la_canada_flintridge.py`). Its 2,000 Logos/citizen-portal rows embed lifecycle and dates in `Permit Summary.StatusValue`. Repair corrects 293 statuses (Completed/Issued/Expired mismatches and missing Expired), fills 73 file dates on Created/Pending rows, fills 1,358 permit dates (Issued StatusValue or PaidValue proxy), and fills/fixes 91 final dates so every Final row has `FINAL_DATE`. After repair: Active PERMIT_DATE 100%, Final PERMIT_DATE 95.2%, Final FINAL_DATE 100%, In Review FILE_DATE 99.5%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` (treating `La Cañada Flintridge` as covered by `data_repair_ca_la_canada_flintridge.py`) was **Lathrop, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Legacy Logos / citizen portal JSON. Core keys: `Permit Summary`, `Payment Summary`, `Permit Details`, `Inspections`, `Location`, `Notes`, `Conditions`, `CONTACT INFORMATION`, `GENERAL CONSTRUCTION`. Optional sections:

| Schema | n | Extra keys |
| --- | ---: | --- |
| `portal` | 1,827 | (core only) |
| `portal_bv` | 63 | Business Valuation |
| `portal_bv_prod` | 59 | BV + Permit Category / Production Permits |
| `portal_coo` | 23 | Certificate of Occupancy (+ BV) |
| `portal_bv_prod_coo` | 18 | BV + Category / Production + COO |
| `portal_prod` | 10 | Permit Category / Production Permits |

Canonical fields: `Permit Summary.StatusValue` (label + embedded `on` / `as of` / bare date), `Payment Summary.PaidValue`. `Inspections` in this extract are empty request placeholders (no usable dates).

StatusValue map:

| StatusValue pattern | `STATUS_NORMALIZED` |
| --- | --- |
| Permit Completed on … | Final |
| Permit Issued on … | Active |
| Permit / Application Created … | In Review |
| Pending Payment / Pending Review … | In Review |
| Permit Expired [date] | Inactive |

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,381 / In Review 243 / Active 207 / missing 123 / Inactive 46.

Errors vs StatusValue:

- **Completed → Active (75) / In Review (15):** `STATUS_ORIGINAL` lagged as `permit issued` / `application created` / `pending payment` / `permit created` while StatusValue already said Completed.
- **Issued → In Review (32):** StatusValue Issued but `STATUS_ORIGINAL` still created/pending.
- **Expired → missing (123) / Active (48):** bare `Permit Expired` or `Permit Expired MM/DD/YYYY` was unmapped or left as issued; 46 already Inactive.

Created/Pending rows were already correctly In Review.

### FILE_DATE

Missing on 1,842 / 2,000. Fillable only when StatusValue is Created/Pending (application / as-of date):

- Created: 122/126 already matched StatusValue date; 3 missing with dated StatusValue → fillable; 1 undated `Permit Created` → not fillable.
- Pending: 0/70 present; all 70 have StatusValue dates → fillable.
- Issued/Completed/Expired StatusValue dates are issuance, completion, or expiry — not filing dates. A few Issued/Completed rows already carry earlier FILE_DATE values (likely upstream application stamps) and were left as-is.

### PERMIT_DATE

Missing on 1,793 / 2,000. Present Active Issued rows already matched the Issued StatusValue date (84/84). Gaps:

- 32 Issued (mislabeled In Review) → fill from Issued date after status fix.
- 1,388 Completed missing PERMIT with PaidValue → fill PaidValue when `PaidValue ≤` Completed date (payment as issuance proxy; same convention as Manteca).
- 62 Completed with PaidValue after completion and 8 with no usable PaidValue (`Not paid` / empty) → not fillable.
- Existing PERMIT on Completed→Active mislabels retained (no PaidValue overwrite when already present).

### FINAL_DATE

Present on 1,381 Final rows; 1,380 matched Completed StatusValue date. One Final row had `FINAL_DATE=2022-05-27` vs StatusValue `05/01/2024` → fix to StatusValue. 90 Completed mislabeled Active/In Review lacked FINAL → fill after status fix. No spurious FINAL on non-Completed rows.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_lathrop.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/lathrop_repair_summary.csv`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 123 | 170 | 123 → 0 |
| FILE_DATE | 73 | 0 | 1,842 → 1,769 |
| PERMIT_DATE | 1,358 | 0 | 1,793 → 435 |
| FINAL_DATE | 90 | 1 | 619 → 529 |

Status after: Final 1,471 / Inactive 217 / In Review 196 / Active 116 (1:1 with StatusValue kind).

After repair:

- FILE_DATE: In Review 195 / 196 (99.5%); Active 25 / 116; Final 11 / 1,471; Inactive 0 / 217
- PERMIT_DATE: Active 116 / 116 (100%); Final 1,401 / 1,471 (95.2%)
- FINAL_DATE: Final 1,471 / 1,471 (100%); none on non-Final
- Remaining ideal gaps: 1 In Review without FILE (`Permit Created` undated); 70 Final without PERMIT (62 PaidValue after completion, 8 no paid); Issued/Completed/Expired FILE_DATE unavailable in DATA
