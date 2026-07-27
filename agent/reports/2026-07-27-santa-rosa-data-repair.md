# Santa Rosa (CA) data repair

**Summary:** Santa Rosa was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status corrections (**FIXED 6**): three `Finaled` rows still labeled Active from stale `STATUS_ORIGINAL=issued`, two `Issued` rows labeled In Review, and one `Withdrawn` row labeled Active. `FILE_DATE` already matched `DATA.date` for all 2,000 rows (no changes). `PERMIT_DATE` gained **FILLED 2** on the Issued→Active corrections. `FINAL_DATE` missingness fell from **502 → 500** (**FILLED 3 · FIXED 25**): filled Close dates on the three status-corrected Finaled rows, corrected 24 Final rows that used an Inspections Complete date instead of the later Closed / Close date, and cleared one spurious FINAL on an Active (Issued) row. Remaining Final gaps are TBD-only inspection/close shells; one Active `Approved` row has no Issued event.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Santa Rosa, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_santa_rosa.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Civic Access scrapes with top-level keys `status`, `date`, `tasks`, `more_details`, `search_data`, etc. Sub-schemas reflect which date sources are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,991 | Dated workflow events under `tasks` |
| `accela_shell` | 7 | Tasks present but no dated events |
| `accela_partial` | 2 | Missing inspections / conditions / fees_details keys |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` |
| `FILE_DATE` | `DATA.date` (fallback: `search_data['Date']`) |
| `PERMIT_DATE` | `Permit Issuance` → Issued (else Revision Issued) |
| `FINAL_DATE` | `Closed` / Close; else `Inspections` / Inspections Complete |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,502 · Active 223 · Inactive 206 · In Review 69 · missing 0

Upstream `STATUS_NORMALIZED` tracks `STATUS_ORIGINAL`, which can lag the live Accela `DATA.status` / `search_data.Status`. Six mismatches:

| `DATA.status` | Was | Expected | n |
| --- | --- | --- | ---: |
| Finaled | Active | Final | 3 |
| Issued | In Review | Active | 2 |
| Withdrawn | Active | Inactive | 1 |

When present, `DATA.status` maps cleanly:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled | Final |
| Issued, Issued - Deferred, Approved | Active |
| In Plan Review, Waiting for Applicant, Plan Review Approved, Pending, Plans Received, Applied, Open | In Review |
| Expired, Withdrawn, Expired Plan Review | Inactive |

**After:** Final 1,505 · Active 221 · Inactive 207 · In Review 67 · missing 0  
Flags: **FILLED 0 · FIXED 6**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA.date` (and `search_data['Date']` on the same calendar day).
- `Application Submittal` / Accepted can be later than `DATA.date` (~182 rows); the Accela record date is the correct application/submittal date.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 125 missing (6.3%). Among Active/Final: 12 / 1,725 missing.

Root cause for the two fillable gaps: Issued rows mis-normalized as In Review, so upstream skipped issuance. Canonical source is earliest `Permit Issuance` / Issued (1,874 rows have this event; when present it already matched `PERMIT_DATE`).

**After:** 123 missing (6.2%). Active 99.5% populated · Final 99.3%.  
Flags: **FILLED 2 · FIXED 0**

Not repairable: 11 Finaled rows and 1 Active `Approved` row lack a dated Permit Issuance / Issued event (one Finaled has Issued marked Expired only; Approved never reached issuance).

### FINAL_DATE

**Before:** 502 missing (25.1%). Among Final: 5 / 1,502 missing. One Active (Issued) row incorrectly carried a FINAL_DATE from Closed / Close.

Root cause: upstream often stored the earliest `Inspections` / Inspections Complete date. When a later `Closed` / Close exists, Close is the better completion/signoff date. Three Finaled→Active mislabels also left FINAL null despite Close events.

Repairs:
1. Fill / correct from latest Closed / Close, else latest Inspections / Inspections Complete.
2. Clear FINAL_DATE when effective status is not Final (**FIXED** to null).

**After:** 500 missing (25.0%). Final 99.7% populated · Active/In Review/Inactive 0%.  
Flags: **FILLED 3 · FIXED 25** (24 date corrections to Close + 1 clear on Active)

Not repairable: 5 Finaled rows with Inspections/Closed events marked TBD only (no usable date).

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 6 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 2 | 0 | 125 | 123 |
| FINAL_DATE | 3 | 25 | 502 | 500 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_santa_rosa.py`
