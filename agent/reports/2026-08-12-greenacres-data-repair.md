# Greenacres (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Greenacres was first. Its DATA is a Logos/TRAKiT-style payload whose lifecycle signal lives in `Permit Summary.StatusValue` (with an embedded date on nearly every row). STATUS_NORMALIZED was already correct for all 2,000 rows. FILE_DATE was missing on 1,966 rows; 517 were FILLED and 2 FIXED, mainly from `Permit Details.Application Received Date` on the newer schema subset, plus a small number of Notes / Pending Payment fallbacks. PERMIT_DATE is complete for Active and unavailable for Final (no IssueDate; PaidValue is fee payment). FINAL_DATE was already complete and correct for all Final rows.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Greenacres, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_greenacres.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_greenacres_repaired.parquet`

## DATA schema

All 2,000 rows share the nested Logos key set (`Permit Summary`, `Permit Details`, `Inspections`, `Notes`, `Conditions`, `Payment Summary`, …). No flat sibling schema in this sample. Content variants differ by StatusValue lifecycle and whether `Permit Details` includes `Application Received Date` (present on 489 rows).

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `logos_completed` | 1,483 | `Permit Completed on …`, no Application Received Date field |
| `logos_completed_app` | 396 | Completed + Application Received Date |
| `logos_issued_app` | 55 | Issued + Application Received Date |
| `logos_issued` | 15 | Issued, no Application Received Date |
| `logos_created_app` | 26 | Application/Permit Created + Application Received Date |
| `logos_created` | 10 | Created with status date only (incl. 2 bare `Application Created`) |
| `logos_pending_app` | 12 | Pending Payment + Application Received Date |
| `logos_pending` | 3 | Pending Payment with as-of date only |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Permit Summary.StatusValue` base text |
| FILE_DATE | `Permit Details.Application Received Date`; else Created status date; else Application Rcvd / APPLICATION RECEIVED notes; else earliest non-Microfilm/Historical Notes / Application Routed ≤ lifecycle date; else Pending Payment as-of date |
| PERMIT_DATE | Issued status date only |
| FINAL_DATE | Completed status date; else latest Completed+Pass final-ish inspection |

StatusValue bases → normalized: Completed→Final; Issued→Active; Pending Payment / Created / Application Created→In Review; Expired→Inactive (none in sample).

## Field assessments

### STATUS_NORMALIZED

**0 missing.** Cross-check of StatusValue base / STATUS_ORIGINAL vs STATUS_NORMALIZED found **0 mismatches**. STATUS_ORIGINAL values (`permit completed`, `permit issued`, `application created`, `pending payment`, `permit created`) already map cleanly.

**0 FILLED / 0 FIXED.** Distribution unchanged: Final 1,879; Active 70; In Review 51.

### FILE_DATE

Ideal: populated for all records.

- Before: **1,966 missing**. The 34 present rows are mostly Application Created / Permit Created; two Permit Created rows used the create stamp while Application Received Date was earlier → **2 FIXED**.
- Newer Permit Details schema exposes `Application Received Date` on 489 rows — primary fill source. Older Completed rows omit that field; Notes are sparse / often archival and rarely yield a usable submittal stamp.
- **517 FILLED** (68 Active, 432 Final, 17 In Review). Remaining gap: **1,449** rows, almost all older Final records without Application Received Date or usable Notes.
- Two Active Issued rows still lack FILE_DATE (no Application Received Date / usable Notes).

Coverage after repair: Active 97.1%; Final 23.0%; In Review 100% (overall 27.6%). Date-order inversions (FILE>PERMIT, FILE>FINAL): 0.

### PERMIT_DATE

Ideal: populated for Active and Final.

- All 70 Active rows already had PERMIT_DATE equal to `Permit Issued on …` — **0 FILLED / 0 FIXED**.
- All 1,879 Final rows lack PERMIT_DATE. StatusValue only embeds the completion date; PaidValue is not a reliable issuance stamp → left missing.
- In Review correctly has no PERMIT_DATE.

Coverage after repair: Active 70/70 (100%); Final 0/1,879 (0%).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All 1,879 Final rows already had FINAL_DATE equal to `Permit Completed on …` — **0 FILLED / 0 FIXED**.
- The 121 missing FINAL_DATE values are exactly the non-Final rows (70 Active + 51 In Review) and are correctly empty.

Coverage after repair: Final 1,879/1,879 (100%); Active / In Review 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 517 | 2 | 1,966 → 1,449 |
| PERMIT_DATE | 0 | 0 | 1,930 → 1,930 |
| FINAL_DATE | 0 | 0 | 121 → 121 |

Remaining structural gaps: Final PERMIT_DATE (no issuance stamp in DATA) and FILE_DATE on older Completed rows without Application Received Date.
