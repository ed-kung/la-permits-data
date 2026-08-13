# Oldsmar (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Oldsmar. Its DATA is a nested city-portal payload (`Parcel` / `Permit` / `Contacts`, optional `Notes` / inspections) with status and dates under `Permit.Main`. `STATUS_NORMALIZED`, `FILE_DATE`, and `PERMIT_DATE` already matched the canonical DATA fields on every recoverable row. The only repair was filling 3 Final `FINAL_DATE` values from the latest COMPLETE inspection when `Closed Date:` was blank/N/A. Remaining date gaps are hollow scrape shells (empty `Permit No` / date fields) or rows that omit `Issued Date:`.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. Oldsmar was the first pair without `agent/scripts/fl/data_repair_fl_oldsmar.py`.

## DATA shape

All 2,001 rows are nested dicts with `Permit.Main` holding colon-suffixed portal fields. Variants (`INFERRED_SCHEMA`):

| Schema | n | Notes |
| --- | ---: | --- |
| `nested_insp_notes` | 931 | `InspectionsCompleted` + `Notes` |
| `nested_notes` | 583 | `Notes` only |
| `nested_insp` | 278 | `InspectionsCompleted` only |
| `nested_minimal` | 148 | `Parcel` + `Permit` + `Contacts` |
| `nested_next_action` | 45 | `Permit.Main` has `Next Action:` (often omits `Issued Date:`) |
| `nested_insp_sched_notes` | 12 | completed + scheduled inspections + notes |
| `nested_sched_notes` | 3 | scheduled inspections + notes |
| `nested_insp_sched` | 1 | completed + scheduled inspections |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Permit.Main["Permit Status:"]` (`ACTIVE`/`COMPLT`/`EXPIRED`/`VOID`) |
| FILE_DATE | `Receipt Date:`; else `Issued Date:` |
| PERMIT_DATE | `Issued Date:` |
| FINAL_DATE | `Closed Date:`; else (Final only) latest COMPLETE `InspectionsCompleted` timestamp |

`Certificate of Occupancy Date:` exists on some rows but differs from `Closed Date:` on 24/113 dual-present cases; upstream `FINAL_DATE` always follows `Closed Date:`, so CO is not used as the primary finalization stamp.

## Field assessments

### STATUS_NORMALIZED

Before/after: Final 1,481; Active 397; Inactive 123; **0 null**. No In Review values.

`STATUS_ORIGINAL` codes (`complt` / `active` / `expired` / `void`) align 1:1 with `Permit Status:` and the normalized labels. No fills or fixes.

### FILE_DATE

Before: 27 missing. When present, every value equals `Receipt Date:` (1,974 matches), including all 294 rows where receipt ≠ issued.

The 27 gaps are hollow shells: empty `Receipt Date:` / `Issued Date:` (26 also have empty `Permit No:`). No alternate application/submittal field in DATA. Flags: **0 FILLED, 0 FIXED**.

After coverage: Active 377/397 (95.0%); Final 1,474/1,481 (99.5%); Inactive 123/123 (100%).

### PERMIT_DATE

Before: 71 missing. When present, every value equals `Issued Date:` (1,930 matches, 0 mismatches).

Gaps: 45 `nested_next_action` / no-`Issued Date:` rows plus 26 empty-string `Issued Date:` shells — no issuance stamp to recover. Flags: **0 FILLED, 0 FIXED**.

After coverage: Active 367/397 (92.4%); Final 1,455/1,481 (98.2%); Inactive 108/123 (87.8%).

### FINAL_DATE

Among Final rows, 1,473 already matched `Closed Date:`; 8 were missing.

- 3 had COMPLETE inspections with timestamps while `Closed Date:` was blank/N/A → **FILLED** from the latest completed inspection (calendar day).
- 5 remain missing: COMPLT shells with empty closed/issued/receipt and no completed inspections.

Inactive rows already carry `FINAL_DATE` = `Closed Date:` on all 123 (void/expired closure stamps retained). Active correctly has none.

Flags: **3 FILLED, 0 FIXED**. Final coverage after repair: 1,476/1,481 (99.7%).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 27 → 27 |
| PERMIT_DATE | 0 | 0 | 71 → 71 |
| FINAL_DATE | 3 | 0 | 405 → 402 |

Ideal-coverage gaps remaining:

- FILE_DATE: **27** (hollow shells; no application date in DATA)
- Active/Final missing PERMIT_DATE: **56** (no `Issued Date:` in DATA)
- Final missing FINAL_DATE: **5** (no Closed Date and no completed inspection)
- STATUS_NORMALIZED: **none**

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_oldsmar.py`
- Repaired sample: `$AGENT_DATA_PATH/oldsmar_repaired_sample.parquet`
