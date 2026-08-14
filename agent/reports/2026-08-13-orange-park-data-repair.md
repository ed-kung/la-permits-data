# Orange Park (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Orange Park**. DATA is a city-portal shell (`Status`, `Request Date`, `permit_id`, empty `inspections` / `reviews` / `fees` / `payments`) with two key-set variants (`city_portal` vs `city_portal_record_type`). Upstream left STATUS_NORMALIZED and all three date fields entirely null. Repair filled STATUS for the 25 rows with a non-blank `Status` (Open→Active, Complete/Closed→Final, Awaiting Schedule→In Review) and filled FILE_DATE from `Request Date` for all 1,860 rows. PERMIT_DATE and FINAL_DATE remain fully missing: nested review/inspection history is empty and there is no Issue / Final Inspection Date field. After repair: FILE_DATE 100%; STATUS null 1,835/1,860 (98.7%); Active/Final PERMIT_DATE 0/24; Final FINAL_DATE 0/6; date-order violations 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Orange Park was the first pair without `agent/scripts/fl/data_repair_fl_orange_park.py` (Sewalls Point and earlier FL jurisdictions already had scripts).

## DATA shape

1,860 rows. Every row has top-level `Request Date`, `Request #`, `permit_id`, project metadata, and nested portal arrays that are always empty in this sample. No `Permit Date` / Issue / Final Inspection Date keys appear. Key-set variants:

| Schema | n |
| --- | ---: |
| `city_portal_applied` | 1,743 |
| `city_portal_record_type_applied` | 117 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status` (`Open`→Active, `Complete`/`Closed`→Final, `Awaiting Schedule`→In Review; blank + dated passed FINAL-ish inspection → Final — none in sample) |
| FILE_DATE | `Request Date` (application / submittal stamp) |
| PERMIT_DATE | Latest approved review/plan_review `completed_date` (Building* preferred); never `Request Date` |
| FINAL_DATE | `Final Inspection Date`, else latest passed FINAL-ish inspection `completed_date` |

## Field assessments

### STATUS_NORMALIZED

Before: 1,860 null (also STATUS_ORIGINAL null). After: 25 FILLED, 1,835 still null.

| Status | n | → STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| (blank) | 1,835 | null | Not fillable — empty inspections, no Final stamp |
| Open | 18 | Active | Filled (sibling portals treat Open as issued/active; pre-issuance is Awaiting Schedule) |
| Complete | 4 | Final | Filled |
| Closed | 2 | Final | Filled |
| Awaiting Schedule | 1 | In Review | Filled |

### FILE_DATE

Before: 1,860 missing. `Request Date` present and parseable on every row. Filled 1,860 → 0 missing. FILE_DATE matches Request Date on 1,860/1,860.

### PERMIT_DATE

Before/after: 1,860 missing. No approved review completions in sample (reviews/plan_reviews always empty). Active/Final still missing PERMIT_DATE: 24/24. Correctly did not copy Request Date into PERMIT_DATE.

### FINAL_DATE

Before/after: 1,860 missing. Inspections always empty; no Final Inspection Date. All 6 Final rows still missing FINAL_DATE.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_orange_park.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 25 | 0 | 1,860 → 1,835 |
| FILE_DATE | 1,860 | 0 | 1,860 → 0 |
| PERMIT_DATE | 0 | 0 | 1,860 → 1,860 |
| FINAL_DATE | 0 | 0 | 1,860 → 1,860 |

Post-repair coverage:

- STATUS_NORMALIZED null: 1,835/1,860 (98.7%)
- FILE_DATE overall: 1,860/1,860 (100%)
- Active/Final PERMIT_DATE: 0/24 (0%)
- Final FINAL_DATE: 0/6 (0%)
- Date order violations (FILE>PERMIT, PERMIT>FINAL, FILE>FINAL): 0

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_orange_park.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_orange_park_repaired.parquet`
