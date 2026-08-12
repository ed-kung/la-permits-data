# North Port (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (parquet encounter order after Delray Beach) was North Port (1,999 records). DATA mixes a legacy city portal (`permit_status` 1,187 + `fees_detail` 15) with Accela Citizen Access (`accela_full` 737 / `accela_basic` 54 / `accela_shell` 6). STATUS_NORMALIZED: 63 FILLED + 79 FIXED (nulls 67→4). FILE_DATE already correct whenever Application Date / Accela Date existed (0 changes; 2 blank-date Inactive rows remain). PERMIT_DATE: 1,017 FIXED — almost all legacy rows were using portal “Permit Date” instead of Issue Date, cutting PERMIT>FINAL inversions from 824 to 0. FINAL_DATE: 642 FILLED + 23 FIXED; Final coverage 93.1% after repair.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: North Port, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` in parquet encounter order)
- Script: `agent/scripts/fl/data_repair_fl_north_port.py`
- Artifact: `AGENT_DATA_PATH/north_port_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `permit_status` | 1,187 | Legacy portal: `permit_status_detail` + `insp_status_detail` |
| `accela_full` | 737 | Accela payload with dated tasks + inspections |
| `accela_basic` | 54 | Accela with dated tasks, empty inspections |
| `fees_detail` | 15 | Legacy `detail` + `fees` only (no permit/insp blocks) |
| `accela_shell` | 6 | Accela shell with no dated task events |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,793; Active 82; null 67; Inactive 34; In Review 23
- **Legacy `permit_status`:** `Status for Permit Number` is usually authoritative (CLOSED / C.O. ISSUED → Final; PERMIT PRINTED → Active; PLAN CHECK / TO BE ISSUED → In Review; PERMIT REVOKED → Inactive). However, 59 CLOSED rows with Application Status VOID / CANCELLED / ABANDONED / EXPIRED/4YEARS were incorrectly Final — FIXED to Inactive. Another 11 rows had wrong labels (e.g. CLOSED/C.O. ISSUED as Active, PERMIT PRINTED as In Review) → FIXED.
- **`fees_detail`:** all 15 STATUS_NORMALIZED null → FILLED from Application Status (9 SUBMITTED→In Review, 4 VOID→Inactive, 2 CANCELLED→Inactive).
- **Accela:** `Schedule Inspection` (48) left null despite Issuance `Issued` → FILLED as Active. `Approved` (9) was Active but has no Issuance event (plans approved, not issued) → FIXED to In Review. Remaining nulls: 4 `accela_shell` rows with null `status`.
- After: Final 1,742; Active 117; Inactive 99; In Review 37; null 4

### FILE_DATE

- Ideal: populated for all records.
- Sources: legacy Application Date; Accela `search_data.Date` / top-level `date` / Application Intake Accepted.
- Already matched the canonical source on every row that has one. **0 FILLED / 0 FIXED.**
- Remaining gaps: 2 legacy Inactive (PERMIT REVOKED) rows with blank Application Date. Among non-null STATUS_NORMALIZED: Active/Final/In Review 100%; Inactive 98.0%.

### PERMIT_DATE

- Ideal: populated for Active and Final.
- **Legacy:** upstream used portal “Permit Date”, which equals Issue Date on only ~142/1,146 rows with both fields; 824 PERMIT>FINAL inversions before repair (all from Permit Date after FINAL). Canonical source is Issue Date; fallback to Permit Date only for Active/Final when Issue is blank and not after FINAL. Clear PERMIT on unissued In Review.
- **Accela:** Issuance `Issued` already matched PERMIT_DATE on nearly all issued rows; Approved→In Review rows correctly stay without PERMIT.
- **0 FILLED + 1,017 FIXED** (1,016 legacy Issue Date overwrites + 1 Accela alignment).
- After: Active 117/117 (100%); Final 1,738/1,742 (99.8%); In Review 1/37 (a Revisions Received row that was previously issued — left as-is). PERMIT>FINAL inversions **824 → 0**.

### FINAL_DATE

- Ideal: populated for Final.
- Before: 987/1,793 Final (55.0%); Accela Final especially sparse (64/703).
- **Legacy:** latest APPROVED inspection with FINAL/FNL/CLOSEOUT in the title; else latest non-NOC APPROVED. Unsupported FINALs cleared; Inactive remaps clear FINAL.
- **Accela:** latest of Closed-task `Closed`, Certification `CO Issued`/`CC Issued`, Inspection-task `Closed`, or Pass inspections with FINAL in the title — recovers the agency closeout date that matches the few rows that already had FINAL.
- **642 FILLED + 23 FIXED.**
- Not repairable: ~118 legacy Final rows with empty / non-APPROVED inspection history; 2 `accela_shell` Final shells; 1 `accela_basic` Final without closeout marks.
- After: Final 1,621/1,742 (93.1%); non-Final FINAL_DATE all null.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 63 | 79 | 67 → 4 |
| FILE_DATE | 0 | 0 | 2 → 2 |
| PERMIT_DATE | 0 | 1,017 | 49 → 64 |
| FINAL_DATE | 642 | 23 | 1,012 → 378 |

Ideal-field coverage after repair (among non-null STATUS_NORMALIZED):

- FILE_DATE: 100% of Active / Final / In Review; 98.0% of Inactive
- PERMIT_DATE: 100% of Active; 99.8% of Final; ~3% of In Review (issued-then-revision edge case)
- FINAL_DATE: 93.1% of Final; 0% of non-Final

Post-repair checks: PERMIT>FINAL inversions 824 → 0; Accela Closed/CO Issued Final rows have FINAL from workflow closeout; legacy PERMIT_DATE aligns with Issue Date; remaining STATUS nulls are empty Accela shells only.

## Artifacts

- `agent/scripts/fl/data_repair_fl_north_port.py`
- `AGENT_DATA_PATH/north_port_repaired_sample.parquet`
