# Fort Worth (TX) data repair

**Summary:** First TX sample jurisdiction without an existing repair script (first-appearance order after Austin and Houston) was **Fort Worth**. DATA is an Accela Civic Access scrape (`status`, `date`, workflow `tasks`, optional `inspections`). Upstream `STATUS_NORMALIZED` often lagged live `DATA.status` (e.g. Finaled/Expired still labeled Active; Opt-Out / Closed By Rule null). After repair: status fully populated and aligned with portal status; FILE_DATE remains 100%; Active PERMIT_DATE 93.4% and Final 99.2%; Final FINAL_DATE rises from 58.8% to **99.5%**; spurious FINAL_DATE on non-Final rows cleared.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Austin and Houston already had repair scripts; **Fort Worth** was the first missing (`agent/scripts/tx/data_repair_tx_fort_worth.py`).

## DATA shape

1,996 rows. Three Accela key-set variants:

| INFERRED_SCHEMA | n |
| --- | ---: |
| `accela_full` | 1,962 |
| `accela_lean` | 32 |
| `accela_contacts` | 2 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `status` (portal) |
| FILE_DATE | `date` (fallback `search_data.Date`) |
| PERMIT_DATE | earliest `Issue Permit` event Marked as Issued / Issued Revision |
| FINAL_DATE | latest `Inspections` Finaled; else latest `Closed` Close / C of O; else latest Approved inspection with “final” in title (Final only) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,297 / Inactive 417 / Active 230 / In Review 39 / **null 13**.

Root cause: `STATUS_NORMALIZED` / `STATUS_ORIGINAL` often reflect a stale search-list snapshot, while live `DATA.status` is newer. Notable mismatches vs `DATA.status`:

| DATA.status | Upstream issue | n (approx) |
| --- | --- | ---: |
| Finaled | labeled Active (STATUS_ORIGINAL often `issued`) | 44 |
| Expired | labeled Active or In Review | 38 |
| Opt-Out / Closed By Rule | STATUS_NORMALIZED null | 13 |
| Awaiting Client Reply / Issued / Executed / Archived / Finaled | other wrong buckets | ~9 |

Mapping used: Finaled/Closed/Executed→Final; Issued/Approved→Active; Pending/Awaiting Client Reply/Plan Review/Incomplete Submittal/Hold/Registered→In Review; Expired/History/Denied/Non-Qualify/Opt-Out/Closed By Rule/Archived→Inactive.

After: Final 1,344 / Inactive 471 / Active 152 / In Review 29 / **null 0**. FILLED 13, FIXED 91.

### FILE_DATE

Before/after: **1,996/1,996** (0% missing). Almost all rows already equal `DATA.date` / `search_data.Date`. **3** rows were off by one day (matched an Application Submittal event instead of the Accela record date) → FIXED to `DATA.date`. No fillable gaps.

### PERMIT_DATE

Before: 253 missing (12.7%). Of those, most were Inactive / In Review / null status (not required). Among Active/Final, a handful lacked Issue Permit Issued events.

| Action | Detail |
| --- | --- |
| FILLED (8) | Issue Permit Issued present but PERMIT_DATE blank |
| FIXED (1) | PERMIT_DATE disagreed with Issue Permit Issued date |

After: missing 245. Coverage by repaired status: Active 142/152 (93.4%), Final 1,333/1,344 (99.2%). Remaining Active gaps are mostly `Approved` (not yet Issued) plus one `Issued` stub with empty Issue events. Remaining Final gaps are legacy Finaled/Closed stubs with no Issue Permit Issued event.

### FINAL_DATE

Before: 1,229 missing (61.6%). Among STATUS=Final, only 762/1,297 (58.8%) had FINAL_DATE — large underfill. Upstream values that existed almost always matched an Inspections Finaled event (often the earliest when multiple Finaled stamps appear).

Issues repaired:
- **575 FILLED** from Closed Close/C of O and/or Inspections Finaled / final-titled approved inspections after status realignment (including former Active→Final rows).
- **16 FIXED**: 11 multi-event Finaled dates normalized to the **latest** Finaled/Close stamp; 5 spurious FINAL_DATE on non-Final rows cleared.

After: Final FINAL_DATE **1,337/1,344 (99.5%)**; Active/In Review/Inactive **0**. The 7 unrepaired Final rows are Historical Sign / XTeam / Occupancy stubs with empty Closed/Inspections events and no final-titled approved inspection.

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_fort_worth.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 13 | 91 | 13 → 0 |
| FILE_DATE | 0 | 3 | 0 → 0 |
| PERMIT_DATE | 8 | 1 | 253 → 245 |
| FINAL_DATE | 575 | 16 | 1,229 → 659 |

Post-repair coverage:

- STATUS_NORMALIZED null: 0
- FILE_DATE overall: 1,996/1,996 (100%)
- Active PERMIT_DATE: 142/152 (93.4%); Final: 1,333/1,344 (99.2%)
- Final FINAL_DATE: 1,337/1,344 (99.5%)
- Non-Final FINAL_DATE: 0 (cleared)

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_fort_worth.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_fort_worth_repaired.parquet`
