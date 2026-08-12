# Dania Beach (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Dania Beach was first. Its DATA is a Logos/TRAKiT-style payload whose lifecycle signal lives in `Permit Summary.StatusValue` (with an embedded date on nearly every row). STATUS_NORMALIZED was already correct for all 2,000 rows. FILE_DATE was missing on 1,949 rows; 525 were FILLED from APPLICATION RECEIVED notes, earliest non-archival Notes, or `Application Routed` conditions (bounded by the StatusValue lifecycle date). PERMIT_DATE is complete for Active and inventable for Final (no IssueDate; PaidValue is fee payment). FINAL_DATE was already complete and correct for all Final rows.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Dania Beach, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_dania_beach.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_dania_beach_repaired.parquet`

## DATA schema

All 2,000 rows share the nested Logos key set (`Permit Summary`, `Permit Details`, `Inspections`, `Notes`, `Conditions`, `Payment Summary`, …). No flat sibling schema in this sample.

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `logos_completed` | 1,840 | `Permit Completed on MM/DD/YYYY` |
| `logos_issued` | 90 | `Permit Issued on MM/DD/YYYY` |
| `logos_created` | 51 | Application/Permit Created with date |
| `logos_pending` | 17 | `Pending Payment as of …` |
| `logos_pending_review` | 1 | `Pending Review as of …` |
| `logos_pending_review_bare` | 1 | bare `Pending Review` |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Permit Summary.StatusValue` base text |
| FILE_DATE | Created status date; else APPLICATION RECEIVED note; else earliest non-Microfilm/Historical Notes / Application Routed condition date ≤ lifecycle date |
| PERMIT_DATE | Issued status date only |
| FINAL_DATE | Completed status date; else latest Completed+Pass final-ish inspection |

StatusValue bases → normalized: Completed→Final; Issued→Active; Pending Payment / Pending Review / Created / Application Created→In Review; Expired→Inactive (none in sample).

## Field assessments

### STATUS_NORMALIZED

**0 missing.** Cross-check of StatusValue base vs STATUS_NORMALIZED found **0 mismatches**. STATUS_ORIGINAL values (`permit completed`, `permit issued`, `application created`, `pending payment`, `permit created`, `pending review`) already map cleanly.

**0 FILLED / 0 FIXED.** Distribution unchanged: Final 1,840; Active 90; In Review 70.

### FILE_DATE

Ideal: populated for all records.

- Before: **1,949 missing**. The 51 present rows are Application Created / Permit Created and already equal the embedded StatusValue date (**0 FIXED**).
- DATA has no dedicated ApplyDate. `Payment Summary.PaidValue` is fee payment — not used.
- Missingness concentrated on Completed (1,840/1,840) and Issued (90/90); also 19 In Review (17 Pending Payment + 2 Pending Review).
- **525 FILLED** from Notes / APPLICATION RECEIVED / Application Routed (467 Final, 44 Active, 14 In Review). Application Routed due-dates match existing FILE_DATE on 28/31 overlap rows (never after FILE_DATE).
- Remaining gap: **1,424** rows with no usable Notes or Application Routed condition on/before the lifecycle date (including 5 In Review pending rows with only a status-as-of stamp and no Notes/Conditions).

Coverage after repair: Active 48.9%; Final 25.4%; In Review 92.9% (overall 28.8%).

### PERMIT_DATE

Ideal: populated for Active and Final.

- All 90 Active rows already had PERMIT_DATE equal to `Permit Issued on …` — **0 FILLED / 0 FIXED**.
- All 1,840 Final rows lack PERMIT_DATE. StatusValue only embeds the completion date; PaidValue is not a reliable issuance stamp → left missing.
- In Review correctly has no PERMIT_DATE.

Coverage after repair: Active 90/90 (100%); Final 0/1,840 (0%).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All 1,840 Final rows already had FINAL_DATE equal to `Permit Completed on …` — **0 FILLED / 0 FIXED**.
- Active and In Review correctly lack FINAL_DATE (nothing to clear).

Coverage after repair: Final 1,840/1,840 (100%); Active / In Review 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 525 | 0 | 1,949 → 1,424 |
| PERMIT_DATE | 0 | 0 | 1,910 → 1,910 |
| FINAL_DATE | 0 | 0 | 160 → 160 |

Date-order checks after repair: FILE_DATE > PERMIT_DATE = 0; FILE_DATE > FINAL_DATE = 0; PERMIT_DATE > FINAL_DATE = 0 (no overlap rows with both permit and final dates).

## Why records were incorrect / missing

1. **FILE_DATE:** Upstream only copied the StatusValue date when the status itself was an application/create event. Issued and Completed StatusValues carry issue/final dates, so FILE_DATE was left blank even when Notes or Application Routed conditions retained a submittal stamp.
2. **PERMIT_DATE on Final:** The portal collapses lifecycle into a single StatusValue string. Once completed, the issuance date is no longer exposed — not an upstream mapping bug, a DATA limitation.
3. **STATUS_NORMALIZED / FINAL_DATE:** Already correctly derived from StatusValue in this sample.
