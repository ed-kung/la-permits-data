# Lake County (CA) data repair

**Summary:** Assessed Lake County's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_lake_county.py`. Lake County uses an Accela Citizen Access portal scrape. FILE_DATE was already complete and correct. STATUS_NORMALIZED had 19 unmapped In Review labels plus 10 rows whose `STATUS_ORIGINAL` lagged `DATA.status` (9 Finaled→Active, 1 Issued→Inactive). FINAL_DATE was filled for 671 Final shells from Passed Final inspections (plus 3 spurious Active FINAL_DATE values cleared). PERMIT_DATE could not be improved: Active/Final gaps lack dated issuance task history.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Lake County, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas (content variants of the same Accela shell):

| Schema | N | Notes |
| --- | --- | --- |
| `portal_application_only` | 771 | Top-level / search date and/or undated workflow; no Issued or Final stamp |
| `portal_issued_finaled` | 546 | Issued + Final Inspection Complete / Passed Final* |
| `portal_final_insp_only` | 512 | Final evidence without dated issuance |
| `portal_issued` | 171 | Issued present, no final-inspection date |

Canonical mappings from DATA:

- `DATA.status` / `search_data.Status` → `STATUS_NORMALIZED`
- Earliest of `DATA.date` / `search_data.Date` / Application Submittal|Acceptance Accepted* → `FILE_DATE`
- Earliest Permit Issuance / Ready to issue permit `Issued`|`Permit Issued` → `PERMIT_DATE`
- Earliest Inspection `Final Inspection Complete` (fallback: Passed Final* inspection) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,635 / Active 197 / In Review 75 / Inactive 74 / missing 19.

Issues:

1. **Missing (19):** `Appl Complete- Routed for Rev` (17) and `Zon Approved` (2) were never mapped → FILLED In Review.
2. **Incorrect (10):** Nine rows have `DATA.status=Finaled` (and matching `search_data.Status`) but `STATUS_ORIGINAL` lagged as issued / permit issued → FIXED Active → Final. One row has `DATA.status=Issued` while ORIG was expired → FIXED Inactive → Active.

Status map: Finaled / Closed / CofO Issued → Final; Issued / Permit Issued → Active; Expired / Void → Inactive; Submitted / Revisions Required / Ready to Issue / In Progress / New / Appl Complete-* / Zon Approved → In Review. Dated issuance promotes In Review → Active. Passed Final inspections alone do **not** promote Issued → Final.

Repair performance: **19 FILLED, 10 FIXED**; missing after: **0**.

After: Final 1,644 / Active 189 / In Review 94 / Inactive 73.

### FILE_DATE

Before: **0 / 2,000 missing**. Every FILE_DATE equals `DATA.date` (and `search_data.Date` when present). Application Submittal Accepted* is never earlier than the top-level date.

Repair: **0 FILLED, 0 FIXED**. Coverage: **100%**.

### PERMIT_DATE

Before: **1,283 / 2,000 missing**. Where an Issued / Permit Issued task mark exists, PERMIT_DATE already matches (717 rows; includes 5 with `Permit Issued` / `Permit issued` rather than bare `Issued`).

Active after status repair: **147 / 189 (77.8%)**. Final: **556 / 1,644 (33.8%)**. Remaining Active/Final gaps have empty or undated Permit Issuance tasks (historic shells and Closed Online Permits with `tasks=null`).

Repair: **0 FILLED, 0 FIXED**.

### FINAL_DATE

Before: **1,625 / 2,000 missing**; only 372 Final rows carried FINAL_DATE (all matching Inspection `Final Inspection Complete`). An additional **662** Finaled shells had a Passed Final* inspection that was never copied into FINAL_DATE; after promoting 9 Finaled→Final rows, **671 FILLED**. Three Active Issued shells incorrectly carried FINAL_DATE → cleared (**3 FIXED**).

Final coverage after repair: **1,043 / 1,644 (63.4%)**. Remaining Final gaps are Closed Online Permits (no inspections) and Finaled shells with no Final* inspection / Final Inspection Complete mark.

## Repair script

`agent/scripts/ca/data_repair_ca_lake_county.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 19 | 10 | 19 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 1,283 | 1,283 |
| FINAL_DATE | 671 | 3 | 1,625 | 957 |

### Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_lake_county.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_ca_lake_county_repaired.parquet`

Remaining gaps: Active/Final PERMIT_DATE where Accela has no dated issuance event; Final FINAL_DATE where no Final inspection evidence exists in DATA. One pre-existing PERMIT_DATE &lt; FILE_DATE row (`BLD23-00391`) is unchanged (FILE_DATE matches `DATA.date`).
