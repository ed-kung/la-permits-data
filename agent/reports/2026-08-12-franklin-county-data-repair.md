# Franklin County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Franklin County**. DATA has two portal scrapes (`simple` flat keys vs `rich` with Reviews / Inspections / Permit Details). Upstream left 7 `STATUS_NORMALIZED` nulls (column-shifted shells), mislabeled `TEST` as In Review, left 22 Issued rows with passed Final Inspection as Active, and stored `FILE_DATE` from Reviews.Completion instead of Start on 99 rows. `FINAL_DATE` was entirely null. The repair filled all 7 statuses (plus FIXED 24), filled 1,645 `FILE_DATE` values and FIXED 99 Start/Completion swaps, filled 3 misaligned `PERMIT_DATE` values, and filled 119 `FINAL_DATE` values from passed final inspections. After repair: STATUS 100%; FILE_DATE 95.2% overall (100% on Active/Final); Active/Final PERMIT_DATE 100%; Final FINAL_DATE 11.6% (limited by missing Inspections on most Closed/CO/CC shells).

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Franklin County, FL** → `agent/scripts/fl/data_repair_fl_franklin_county.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `simple_issued` | 1,282 | Flat Status / Issue Date; no Reviews |
| `rich_balanced_issued` | 255 | Rich + Balance Due; issue date, no final insp |
| `rich_issued` | 176 | Rich; issue date, no final insp |
| `rich_issued_finaled` | 97 | Rich; issue + passed final insp |
| `rich_balanced_issued_finaled` | 77 | Rich + Balance Due; issue + final insp |
| `simple_status_only` | 61 | Flat; no parseable Issue Date |
| `rich_status_only` | 36 | Rich; no usable dates |
| `rich_applied` | 16 | Reviews.Start only (no issue date) |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status` / `Status:` (fallback `Sub Type` on misaligned rows); Active→Final when passed `Final Inspection`; In Review→Active when Issue Date present |
| FILE_DATE | `Reviews.Start` else `Issue Date` / `Permit Details["Issue Date:"]` else date-as-Status |
| PERMIT_DATE | `Issue Date` else `Permit Details["Issue Date:"]` else date-as-Status |
| FINAL_DATE | Latest passed final-ish inspection (`Final Inspection`, `Roof - Final`, etc.) |

## Field assessments

### STATUS_NORMALIZED

| Raw Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Issued | 881 | Active (22 with passed Final Inspection) | 22 should be Final |
| Closed | 837 | Final | Correct |
| CO Issued | 107 | Final | Correct |
| Void | 99 | Inactive | Correct |
| CC Issued | 55 | Final | Correct |
| Under Review | 7 | In Review (1 with Issue Date) | Issued row → Active |
| Online Application Received | 4 | In Review | Correct |
| date / work-description garbage | 5 | **null** | Sub Type Closed→Final, Void→Inactive |
| Approved - Awaiting Payment | 1 | **null** | Fill → In Review |
| Reroof / reroof | 2 | **null** | Sub Type Void → Inactive |
| Denied | 1 | Inactive | Correct |
| Incomplete Application | 1 | In Review | Correct |
| TEST | 1 | **In Review** | Sub Type Void → Inactive |

**Root causes:**
1. Scraping misalignment on a handful of simple rows put dates or work descriptions in `Status` and the true lifecycle label in `Sub Type`.
2. Upstream mapper omitted `Approved - Awaiting Payment`.
3. `TEST` was treated as In Review despite `Sub Type = Void`.
4. Issued permits with a passed whole-permit Final Inspection were not upgraded to Final.

**Repair performance:** FILLED 7, FIXED 24; missing 7 → 0.

### FILE_DATE

- Before: missing on **1,741 / 2,000** (87.1%). Present values came only from rich rows with Reviews.
- On 99 rows, upstream stored `Reviews.Completion` rather than `Reviews.Start` (application/submittal). Those were FIXED to Start.
- Remaining gaps filled from Issue Date (top-level or Permit Details) when Reviews.Start was absent — common fallback when the portal exposes no applied date on simple shells.
- After repair: missing **96** (mostly Void / incomplete / Online Application Received shells with no dates). Active/Final coverage **100%**.

**Repair performance:** FILLED 1,645, FIXED 99; missing 1,741 → 96 (95.2% coverage).

### PERMIT_DATE

- Before: missing on **116 / 2,000**; Active/Final already had 0 gaps and matched Issue Date (0 mismatches).
- Gaps were In Review (12), Inactive (97), and null-status (7).
- Filled 3 Final rows from date-as-Status on misaligned Closed shells.
- One Under Review row with Issue Date was upgraded to Active (status FIXED), retaining its PERMIT_DATE.
- In Review correctly has 0% PERMIT_DATE after repair. Inactive retains 3 issued-then-voided dates.

**Repair performance:** FILLED 3, FIXED 0; Active/Final PERMIT_DATE **100%**.

### FINAL_DATE

- Before: missing on **2,000 / 2,000** (100%).
- Filled 119 Final rows from passed final-ish inspections (97 already-Final + 22 Active→Final upgrades).
- Remaining Final gaps (**905**): almost all `Closed` / `CO Issued` / `CC Issued` simple shells with no Inspections array, plus rich Closed rows whose inspection lists lack a final-ish passed item.
- No spurious FINAL_DATE on non-Final statuses after repair.

**Repair performance:** FILLED 119, FIXED 0; Final coverage **11.6%** (119 / 1,024).

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_franklin_county.py`
- Entry point: `data_repair(df)`
- Outputs: overwritten `STATUS_NORMALIZED` / `FILE_DATE` / `PERMIT_DATE` / `FINAL_DATE`; flags `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`}; `INFERRED_SCHEMA`
- Conventions follow `agent/scripts/ny/data_repair_ny_ny.py` and recent FL civic/portal repairs

## Artifacts

- Repaired sample parquet: `AGENT_DATA_PATH/franklin_county_repaired_sample.parquet`
