# Roseville (CA) data repair

**Summary:** Roseville was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status missingness fell from **48 → 1** (**FILLED 47 · FIXED 14**): blank Receipt shells → Inactive; Finaled mislabeled Active and Issued/Approved mislabeled In Review corrected. `FILE_DATE` already matched `DATA.date` for all 2,000 rows (**FILLED 0 · FIXED 0**). `PERMIT_DATE` missingness fell **1,246 → 532** (**FILLED 714**) mainly from OTC `Application Submittal` / Issued and revision `Approved` marks that upstream missed. `FINAL_DATE` gained **FILLED 8 · FIXED 1** (status-fixed Finaled rows + one stale earlier Finaled); Final coverage is **1,146 / 1,407 (81.4%)**. Active PERMIT coverage is **308 / 317 (97.2%)**. One inherent chronology inversion remains (`PERMIT > FINAL` on a re-issuance after final).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Roseville, CA** (n=2,000) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` (index 85 after San Mateo County)
- Script: `agent/scripts/ca/data_repair_ca_roseville.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_roseville_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Citizen Access scrapes with shared top-level keys: `status`, `date`, `tasks`, `search_data`, `inspections`, `more_details`, `record_type`, fees/contacts/conditions, etc. Sub-schemas reflect content richness:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,645 | Dated workflow events under `tasks` |
| `accela_shell` | 306 | Task shells present but no dated events (mostly older Finaled conversions) |
| `accela_receipt` | 47 | Receipt record type; blank Status; Closure shell with empty events |
| `accela_search_only` | 2 | No tasks; dates only in `search_data` / `DATA.date` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (= `search_data['Status']`); blank Receipt → Inactive; else task marks |
| `FILE_DATE` | `DATA.date`; else `search_data['Submitted Date']`; else earliest Application Submittal event |
| `PERMIT_DATE` | `Permit Issuance` → Issued; else `Ready to Issue` → Issued; else `Application Submittal` → Issued; else `Distribution` → Issued OTC; else Revision/Plan/`Approved` → Approved |
| `FINAL_DATE` | Latest `Inspections` → Finaled |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,399 · Active 320 · Inactive 136 · In Review 97 · missing 48

`DATA.status` → expected mapping:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled, FINALED | Final |
| Issued, Issued with Revisions, Approved | Active |
| In Review, Additional Info Required/Provided, Resubmittal Required, On Hold, Open, Ready to Issue, Plans Received | In Review |
| Expired, Withdrawn, Denied, Void | Inactive |

Issues:
1. **48 null `STATUS_NORMALIZED`:** 47 are Receipt records with blank `DATA.status` / `search_data.Status` and empty Closure events → **FILLED Inactive**. 1 Residential Single Family shell (`BD19-5200`) has blank Status and no events → left missing (not repairable).
2. **14 mismatches vs `DATA.status` (FIXED):**
   - Finaled labeled Active (8) — STATUS_ORIGINAL often still `issued`; Inspections already Finaled
   - Issued labeled In Review (4) — STATUS_ORIGINAL lagged (`additional info required` / `in review`)
   - Approved labeled In Review (1)
   - In Review labeled Inactive (1) — STATUS_ORIGINAL `expired` while portal Status is In Review

**After:** Final 1,407 · Active 317 · Inactive 182 · In Review 93 · missing 1  
Flags: **FILLED 47 · FIXED 14**

### FILE_DATE

**Before:** 0 missing (100%).

- `FILE_DATE` equals top-level `DATA.date` for all 2,000 rows (also consistent with `search_data['Submitted Date']` when present).
- No fill or fix needed.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**  
Coverage: **100%**.

### PERMIT_DATE

**Before:** 1,246 missing (62.3%). Among Active/Final: 994 / 1,719 missing (Active 223/320 · Final 771/1,399).

- When `PERMIT_DATE` was already set, it matched `Permit Issuance` / Issued (500) or `Ready to Issue` / Issued (254) exactly — 0 disagreements with those tiers.
- Primary fillable gap: Active/Final rows with OTC `Application Submittal` / Issued (and a few `Distribution` / Issued OTC) that upstream never mapped → majority of the **714 FILLED**.
- Secondary fill: Active `Approved` revisions (`Revision to a Permit` / `Residential Master Plan`) using `Revision Approval` / `Plan Approval` / `Approved` → Approved marks.

Gaps after repair (532 overall; Active 9 · Final 276 still missing) are dominated by:
- **`accela_shell` Finaled rows** (~257+): converted records with empty task events and no Issued mark.
- **Active Issued shells** with TBD-only or empty Permit Issuance events (Fire System / Mechanical).
- **A few Approved Master Plans** without dated Approved marks.

**After:** missing 532 overall; Active **308 / 317 (97.2%)** · Final **1,131 / 1,407 (80.4%)** have `PERMIT_DATE`.  
Flags: **FILLED 714 · FIXED 0**

### FINAL_DATE

**Before:** 862 missing. Among Final: 261 / 1,399 missing (81.3% coverage). 0 spurious finals on non-Final rows.

- Existing `FINAL_DATE` matched `Inspections` / Finaled for 1,137 / 1,138 Final rows with that event; **1 mismatch** used an earlier Finaled (2014-01-13) when a later Finaled (2014-01-14) existed → **FIXED**.
- **FILLED 8:** the 8 Finaled-mislabeled-Active rows, once status-fixed to Final, gain Inspections Finaled dates.
- Remaining Final gaps (261) are almost entirely `accela_shell` / empty-event Finaled records; 3 `accela_tasks` Finaled rows have Issued marks but no Finaled event.

**After:** missing 854 overall; Final **1,146 / 1,407 (81.4%)** have `FINAL_DATE`; Active / In Review / Inactive at 0%.  
Flags: **FILLED 8 · FIXED 1**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 47 | 14 | 48 → 1 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 714 | 0 | 1,246 → 532 |
| `FINAL_DATE` | 8 | 1 | 862 → 854 |

Chronology after repair: `FILE > PERMIT` = 0; `PERMIT > FINAL` = 1 (Permit Issuance 2014-04-02 after Inspections Finaled 2014-01-30 — agency re-issuance; both dates retained from DATA).

## Artifacts

- `agent/scripts/ca/data_repair_ca_roseville.py`
- `AGENT_DATA_PATH/repaired/permits_ca_roseville_repaired.parquet`
