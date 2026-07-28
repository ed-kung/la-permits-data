# Visalia (CA) data repair

**Summary:** Visalia was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status missingness fell from **45 → 0** (**FILLED 45 · FIXED 0**): unmapped labels `FINALMST`, `Final - ATMC`, `Issued Deferred`, and `CR` were filled. `FILE_DATE` already matched Accela sources for all 2,000 rows (**FILLED 0 · FIXED 0**). `PERMIT_DATE` missingness fell **1,587 → 1,460** (**FILLED 127**) from `Pending Issuance` / `Permit Issuance` / `Application Submittal` Issued marks on Active/Final rows. `FINAL_DATE` missingness fell **1,442 → 546** (**FILLED 897 · FIXED 7**); Final coverage is **1,454 / 1,501 (96.9%)**, with Active / In Review / Inactive at 0 final dates. No chronology inversions remain (**FILE>PERMIT=0**, **PERMIT>FINAL=0**).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Visalia, CA** (n=2,000) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/ca/data_repair_ca_visalia.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_visalia_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Citizen Access scrapes with the same top-level keys: `status`, `date`, `tasks`, `search_data`, `inspections`, `more_details`, `record_type`, fees/contacts/conditions, etc. Sub-schemas reflect which date sources are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_shell` | 1,246 | Task shells present but no dated events (mostly pre-~2018 converted records) |
| `accela_tasks` | 740 | Dated workflow events under `tasks` |
| `accela_search_only` | 14 | No tasks; dates only in `search_data` / `DATA.date` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (= `search_data['Status']`); fallback: task event marks |
| `FILE_DATE` | `search_data['Date']`; else `DATA.date`; else earliest Application Submittal event |
| `PERMIT_DATE` | `Pending Issuance` → Issued; else `Permit Issuance` → Issued; else `Application Submittal` → Issued |
| `FINAL_DATE` | `Inspections`/`Inspection` → Finaled / Finaled - ATMC / Final - ATMC; else latest approved FINAL inspection `Status Date` (`AP` / `Approved` / `PA`) |

Implementation note: Accela events carry both `Status` (`Due on`) and `Marked as` (workflow result). The repair reads `Marked as` first; reading `Status` first would miss all Issued/Finaled marks.

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,461 · Inactive 305 · Active 180 · missing 45 · In Review 9

`DATA.status` → expected mapping:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| FINAL, Finaled, FINALMST, Final - ATMC | Final |
| ISSUED, Issued, Issued Deferred, APPROVED | Active |
| In Review, Ready to Issue, Pending Resubmittal, Pending Issuance, CR | In Review |
| Expired, EXPIRED, Permit Expired, CANCEL, Withdrawn, Closed - Withdrawn, WITHDRWN, Void, DENIED, Denied | Inactive |

Issues:
1. **45 null `STATUS_NORMALIZED` (all FILLED):** portal labels not previously mapped — `FINALMST` (23) → Final, `Final - ATMC` (17) → Final, `Issued Deferred` (4) → Active, `CR` (1) → In Review (applied-only shell).
2. **0 mismatches** among already-populated rows: when `STATUS_NORMALIZED` was set, it already agreed with the map.

**After:** Final 1,501 · Inactive 305 · Active 184 · In Review 10 · missing 0  
Flags: **FILLED 45 · FIXED 0**

### FILE_DATE

**Before:** 0 missing (100%).

- `FILE_DATE` equals `search_data['Date']` and top-level `DATA.date` for all 2,000 rows (0 mismatches).
- No fill or fix needed.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**  
Coverage: **100%**.

### PERMIT_DATE

**Before:** 1,587 missing (79.3%). Among Active/Final: 1,279 / 1,641 missing.

- When an Issued workflow mark exists, existing `PERMIT_DATE` always matched it (413/413; 0 disagreements).
- Primary fillable gap: Active/Final rows with `Pending Issuance` / `Permit Issuance` / `Application Submittal` → Issued but empty `PERMIT_DATE` → **FILLED 127** (116 Final · 11 Active; all `accela_tasks`).
- `Application Submittal` → Issued is used as a fallback for over-the-counter / short workflow records (often same-day as `FILE_DATE`).

Gaps after repair (1,189 Active/Final still missing) are dominated by:
- **`accela_shell` Final rows** (~1,039): converted records with TBD-only task events and no Issued mark.
- **ISSUED Active shells** without dated Issued events.
- **Issued Deferred** (4): Active but not yet Issued — correctly left missing.

**After:** missing 1,460 overall; Active 48/184 (26.1%) · Final 448/1,501 (29.8%) have `PERMIT_DATE`.  
Flags: **FILLED 127 · FIXED 0**

### FINAL_DATE

**Before:** 1,442 missing (72.1%). Among Final: 920 / 1,461 missing (63.0%).

Root causes:
1. Upstream often populated `FINAL_DATE` only from `Inspections` → Finaled task events (~558), missing the large set of older Final shells whose finaling signal is an approved FINAL inspection (`AP`/`Approved`/`PA` Status Date).
2. A few Finaled rows stored the *first* Finaled mark rather than the latest (re-finaled permits).
3. One Expired row carried a spurious `FINAL_DATE` (cleared).

Repairs:
1. Prefer latest `Inspections`/`Inspection` → Finaled / Finaled - ATMC / Final - ATMC.
2. Else latest approved FINAL inspection `Status Date`.
3. Clear `FINAL_DATE` on non-Final records.

**After:** missing 546 overall; Final 1,454/1,501 (96.9%) have `FINAL_DATE`. Remaining Final gaps (47): mostly `FINALMST` shells with no inspections (23), plus Finaled/FINAL shells without an approved FINAL inspection.  
Flags: **FILLED 897 · FIXED 7** (6 latest-Finaled corrections + 1 spurious clear on Expired)

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 45 | 0 | 45 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 127 | 0 | 1,587 → 1,460 |
| `FINAL_DATE` | 897 | 7 | 1,442 → 546 |

Chronology after repair: **FILE > PERMIT = 0**, **PERMIT > FINAL = 0**.
