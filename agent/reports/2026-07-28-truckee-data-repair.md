# Truckee (CA) data repair

**Summary:** Truckee was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script (La Cañada Flintridge already covered by `data_repair_ca_la_canada_flintridge.py`). Its 2,000 Logos/citizen-portal rows embed lifecycle and dates in `Permit Summary.StatusValue`. Repair corrects 22 statuses (Completed/Issued mismatches), fills 61 file dates on Created/Pending rows (and fixes 2 mismatches), fills 1,440 permit dates (mostly PaidValue on Completed rows), and fills 15 final dates so every Final row has `FINAL_DATE`. After repair: Active PERMIT_DATE 100%, Final PERMIT_DATE 99.4%, Final FINAL_DATE 100%, In Review FILE_DATE 98.6%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` (treating `La Cañada Flintridge` as covered by `data_repair_ca_la_canada_flintridge.py`) was **Truckee, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Legacy Logos / citizen portal JSON. All 2,000 sample rows share one key set (`portal`): `Permit Summary`, `Payment Summary`, `Permit Details`, `Inspections`, `Location`, `Notes`, `Conditions`, `CONTACT INFORMATION`, `GENERAL CONSTRUCTION`. Optional Lathrop-style sections (Business Valuation, Certificate of Occupancy, Permit Category / Production Permits) are absent here.

Canonical fields: `Permit Summary.StatusValue` (label + embedded `on` / `as of` date), `Payment Summary.PaidValue`. `Inspections` in this extract are empty (no usable dates).

StatusValue map:

| StatusValue pattern | `STATUS_NORMALIZED` |
| --- | --- |
| Permit Completed on … | Final |
| Permit Issued on … | Active |
| Permit / Application Created … | In Review |
| Pending Payment / Pending Review … | In Review |

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,440 / Active 331 / In Review 229 / missing 0. Status was mapped from `STATUS_ORIGINAL`, which sometimes lagged behind `StatusValue`:

| Current → expected | n | Cause |
| --- | ---: | --- |
| Active → Final | 13 | `STATUS_ORIGINAL=permit issued` while StatusValue already Completed |
| In Review → Active | 7 | `STATUS_ORIGINAL` still pending/created while StatusValue Issued |
| In Review → Final | 2 | `STATUS_ORIGINAL` pending/created while StatusValue Completed |

Created/Pending/Issued/Completed rows that already matched StatusValue were left unchanged. No Expired labels in this sample.

### FILE_DATE

Missing on 1,839 / 2,000. Fillable only when StatusValue is Created/Pending (application / as-of date):

- Application Created / Permit Created: most already matched StatusValue date; 61 missing with dated StatusValue → fillable; 2 disagreed with StatusValue → FIXED; 3 undated `Permit Created` → not fillable.
- Pending Payment / Pending Review: StatusValue `as of` dates used to fill missing FILE_DATE.
- Issued/Completed StatusValue dates are issuance or completion — not filing dates. A few Issued/Completed rows already carry earlier FILE_DATE values and were retained.

### PERMIT_DATE

Missing on 1,669 / 2,000. Active Issued rows already matched the Issued StatusValue date (318/318 correctly labeled; 7 Issued mislabeled In Review filled after status fix → Active PERMIT_DATE 100%). Gaps on Final:

- 1,440 Completed missing PERMIT with usable PaidValue → FILLED PaidValue when `PaidValue ≤` Completed date (payment as issuance proxy; same convention as Lathrop/Manteca).
- 7 Completed with PaidValue after completion and 2 with `"Not paid"` → PERMIT_DATE stays missing (9 Final rows, 99.4% coverage).
- Existing PERMIT on Completed→Active mislabels retained (no PaidValue overwrite when already present).

### FINAL_DATE

Present on 1,440 Final rows; all matched Completed StatusValue date. 15 Completed mislabeled Active/In Review lacked FINAL → FILLED after status fix. No spurious FINAL on non-Completed rows; non-Final FINAL_DATE cleared if present (none in sample).

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_truckee.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/truckee_repair_summary.csv`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 22 | 0 → 0 |
| FILE_DATE | 61 | 2 | 1,839 → 1,778 |
| PERMIT_DATE | 1,440 | 0 | 1,669 → 229 |
| FINAL_DATE | 15 | 0 | 560 → 545 |

Post-repair coverage by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 325 | 1.2% | 100% | 0% |
| Final | 1,455 | 0.1% | 99.4% | 100% |
| In Review | 220 | 98.6% | 0% | 0% |

Remaining gaps are structural: Issued/Completed rows lack an application date in DATA; 9 Final rows lack a usable PaidValue issuance proxy; 3 undated `Permit Created` rows lack FILE_DATE.
