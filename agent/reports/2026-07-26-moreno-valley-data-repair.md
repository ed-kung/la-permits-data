# Moreno Valley (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Moreno Valley — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 1,999 sample rows are Accela Citizen Access scrapes (`status` / `date` / `tasks`, optionally `inspections`). Status is now fully populated (FILLED 102 · FIXED 96): the largest corrections were 55 `RESOLVED` weed-abatement rows wrongly labeled In Review (→ Final) and Active rows whose `DATA.status` or workflow was already final (`Inspection Complete`, lagged `Closed`/`Final`). `FILE_DATE` already matched `DATA.date` on every row. `PERMIT_DATE` gained 11 fills from Issued / Issued Plans task events; coverage remains low on Active (37%) and Final (29%) because most code cases, historical shells, and Approved entitlements have no dated issuance. `FINAL_DATE` was the main win: 810 fills from Inspections Final*/Closed, code-enforcement Closed, fire-annual Passed/Results OK, and historical Status=`A` finals, plus 4 date fixes; Final coverage rose to 1,097 / 1,237 (88.7%), and non-Final rows carry 0% `FINAL_DATE`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Moreno Valley, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_moreno_valley.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/moreno_valley_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `tasks_only` | 1,014 | Workflow tasks present; no inspections list |
| `tasks_inspections` | 984 | Tasks + inspections |
| `inspections_only` | 1 | Inspections without usable tasks |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (case-insensitive map; Active→Final if final workflow events exist) |
| `FILE_DATE` | `DATA.date` (fallback: `search_data['Date']`) |
| `PERMIT_DATE` | Earliest `Ready to Issue` / `Permit Issuance` / `Issuance` / `Permit Issued` **Issued**; else `Ready to Issue Plans` / Issued Plans; else OTC Application Submittal Issued |
| `FINAL_DATE` | Latest Inspections Final*/Closed; Inspection Closed/Final Inspection; Final Inspection Final/C of O; fire-annual Passed / Results OK; plan-check Review Completed; historical FINAL/COFO insp with Status `A`/`PA`/`CLOS` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,098 · Active 518 · In Review 184 · missing 102 · Inactive 97

Issues:
1. **102 unmapped `DATA.status` values** left `STATUS_NORMALIZED` null (`Record Created` 33, `Passed Inspection` 22, abatement completed, `M_APRVD`, `Unfounded`, invoice/taxroll codes, etc.).
2. **`RESOLVED` → In Review (55)** — historical fire weed records (`F_WEED/*`); past-tense resolution should be **Final**.
3. **Lagged Active labels** — `Inspection Complete` (8), `Closed`/`Final`/`Finaled` with STATUS_ORIGINAL still issued/active (12), plus rows whose workflow already shows Final/Closed/Passed while portal status lags.
4. **One `Permit Issued` still In Review** and one `Expired` still Active → FIXED.

**After:** Final 1,237 · Active 488 · In Review 176 · Inactive 98 · missing 0  
Flags: **FILLED 102 · FIXED 96**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA.date` at calendar-day resolution. `search_data['Date']` agrees where present.
- No fills or fixes.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 1,436 missing (71.8%). Where present, values agree with the earliest Issued task event (555/555 with an Issued event; 8 present without a dated Issued task).

Repairs:
- Fill Active/Final gaps from Issued / Issued Plans (**11 FILLED**, mostly Land Dev Utility Daily / encroachment and one OTC Energy).

Remaining Active/Final gaps are structural: code cases (`Closed`), inspection programs (`Inspection Deferred`/`Scheduled`), Approved entitlements without issuance, and pre-migration historical shells (`FINAL`/`COMPLETE`) with empty task event dates.

**After:** missing 1,425. Active 181/488 (37.1%) · Final 360/1,237 (29.1%).  
Flags: **FILLED 11 · FIXED 0**

### FINAL_DATE

**Before:** 1,712 missing; only 263/1,098 Final rows had `FINAL_DATE` (24.0%); **6 Active** rows carried a final date (mostly `Inspection Complete`).

Repairs:
- Fill Final gaps from workflow Closed/Final/Passed and historical Status=`A` finals (**810 FILLED**).
- Align a few existing finals to the later true C of O / Sprinkler Final / Final With CO stamp (**4 FIXED**).
- Clear spurious finals on rows that remain non-Final after status repair (absorbed into Final promotions where appropriate).

Remaining Final gaps (140): 55 `RESOLVED` weed shells with no dated close event; 31 historical `COMPLETE` fire shells without dated final insp; 13 `Completed` plan revisions without Review Completed; 10 owner-abatement / 9 `CLOSED` planning / other shells with Notes-only workflows.

**After:** missing 902 overall. Final 1,097/1,237 (88.7%); Active / In Review / Inactive 0%.  
Flags: **FILLED 810 · FIXED 4**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 102 | 96 | 102 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 11 | 0 | 1,436 → 1,425 |
| `FINAL_DATE` | 810 | 4 | 1,712 → 902 |

Ideal-field coverage after repair:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 37.1% | 0% (correct) |
| Final | 100% | 29.1% | 88.7% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | n/a | 0% |

## Artifacts

- `agent/scripts/ca/data_repair_ca_moreno_valley.py`
- `AGENT_DATA_PATH/moreno_valley_repaired_sample.parquet`
