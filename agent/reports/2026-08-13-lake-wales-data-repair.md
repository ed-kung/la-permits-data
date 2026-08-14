# Lake Wales (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Lake Wales**. DATA is the nested city-portal payload (`Parcel` / `Permit` / `Contacts`, optional inspections/notes) with status and dates under `Permit.Main`. Upstream dates already match `Receipt Date:` / `Issued Date:` / `Closed Date:` whenever those fields are present. Repairs fill 3 null statuses (`INACTV`→Inactive, `SM-ACT`→Active) and 114 Final `FINAL_DATE` values from the latest COMPLETE inspection when `Closed Date:` is blank. Remaining gaps are hollow scrape shells or rows that omit issuance/receipt stamps in DATA. After repair: Final FINAL_DATE **1,692/1,697 (99.7%)**.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. Lake Wales was the first pair without `agent/scripts/fl/data_repair_fl_lake_wales.py`.

## DATA shape

All 2,000 rows are nested dicts. Variants (`INFERRED_SCHEMA`):

| Schema | n | Notes |
| --- | ---: | --- |
| `nested_insp` | 1,486 | `InspectionsCompleted` only |
| `nested_minimal` | 247 | `Parcel` + `Permit` + `Contacts` |
| `nested_insp_sched` | 134 | completed + scheduled inspections |
| `nested_next_action` | 121 | `Permit.Main` has `Next Action:` (often omits `Issued Date:`) |
| `nested_empty_main` | 5 | `Permit.Main` missing/empty scrape shells |
| `nested_notes` | 4 | `Notes` only |
| `nested_insp_notes` | 2 | inspections + notes |
| `nested_insp_req` | 1 | inspections + `InspectionsRequested` |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Permit.Main["Permit Status:"]` (`ACTIVE`/`COMPLT`/`EXPIRED`/`VOID`/`INACTV`/`SM-ACT`) |
| FILE_DATE | `Receipt Date:`; else `Issued Date:` |
| PERMIT_DATE | `Issued Date:` |
| FINAL_DATE | `Closed Date:`; else (Final only) latest COMPLETE `InspectionsCompleted` timestamp |

`Certificate of Occupancy Date:` exists under `Occupancy & Warranty` but is empty on the rows still missing FINAL after Closed/inspection fallback, so CO is not used.

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,697; Active 163; Inactive 132; null 8. No In Review values.

| Issue | n | Repair |
| --- | ---: | --- |
| `INACTV` unmapped → null | 2 | FILLED → Inactive |
| `SM-ACT` unmapped → null (issued, open permit) | 1 | FILLED → Active |
| Empty `Permit.Main` / blank Permit Status | 5 | not repairable |

When present, `STATUS_ORIGINAL` codes align 1:1 with `Permit Status:` and the upstream normalized labels (`complt`→Final, `active`→Active, `expired`/`void`→Inactive). No incorrect non-null statuses found.

Flags: **3 FILLED, 0 FIXED**. After: Final 1,697; Active 164; Inactive 134; null 5.

### FILE_DATE

Before: 194 missing. When present, every value equals `Receipt Date:` (1,806 matches, 0 mismatches).

The 194 gaps have empty/missing `Receipt Date:` and also empty/missing `Issued Date:` — no alternate application/submittal field in DATA. Six rows have `Receipt Date:` after `Issued Date:` in the portal itself (not an ingestion error).

Flags: **0 FILLED, 0 FIXED**. After coverage: Active 105/164 (64.0%); Final 1,578/1,697 (93.0%); Inactive 123/134 (91.8%).

### PERMIT_DATE

Before: 326 missing. When present, every value equals `Issued Date:` (1,674 matches, 0 mismatches).

Gaps are concentrated in `nested_next_action` / no-`Issued Date:` ACTIVE shells and hollow COMPLT/VOID rows — no issuance stamp to recover. Eleven rows have portal `Issued Date:` after `Closed Date:` (source anomaly retained).

Flags: **0 FILLED, 0 FIXED**. After coverage: Active 68/164 (41.5%); Final 1,517/1,697 (89.4%); Inactive 89/134 (66.4%).

### FINAL_DATE

Among Final rows, 1,578 already matched `Closed Date:`; 119 were missing.

- 114 had COMPLETE inspections with timestamps while `Closed Date:` was blank/N/A → **FILLED** from the latest completed inspection (calendar day).
- 5 remain missing: COMPLT shells with empty Permit No / closed / issued / receipt and no inspections.

Inactive rows already carry `FINAL_DATE` = `Closed Date:` on 120/134 (void/expired closure stamps retained). Active correctly has none.

Flags: **114 FILLED, 0 FIXED**. Final coverage after repair: **1,692/1,697 (99.7%)**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 0 | 8 → 5 |
| FILE_DATE | 0 | 0 | 194 → 194 |
| PERMIT_DATE | 0 | 0 | 326 → 326 |
| FINAL_DATE | 114 | 0 | 302 → 188 |

Ideal-coverage gaps remaining:

- FILE_DATE: **194** (no Receipt/Issued in DATA)
- Active/Final missing PERMIT_DATE: **276** (no `Issued Date:` in DATA)
- Final missing FINAL_DATE: **5** (hollow COMPLT shells)
- STATUS_NORMALIZED: **5** (empty `Permit.Main`)

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_lake_wales.py`
- Repaired sample: `$AGENT_DATA_PATH/lake_wales_repaired_sample.parquet`
