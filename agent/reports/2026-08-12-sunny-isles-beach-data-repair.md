# Sunny Isles Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Sunny Isles Beach**. DATA is a SmartGov community portal payload (`Build Status` / `My Project` dates; `Permit Details` and `Permit Inspections` are empty in this sample). Upstream left 368 `STATUS_NORMALIZED` nulls (especially `REVISED`, null Build Status, and some `Expired*`) and often ignored Closed stamps on `RENEWED` / `ACTIVE` / ready-to-issue rows. Present dates already matched `My Project.Submitted` / `Issued` / `Closed` almost everywhere. The repair filled 361 statuses and fixed 56, filled 1 `FILE_DATE`, 27 `PERMIT_DATE`, and 10 `FINAL_DATE` values, and fixed 1 stale `FINAL_DATE`. After repair: STATUS 99.6%; FILE_DATE 99.6%; Active/Final PERMIT_DATE 100%/99.6%; Final FINAL_DATE 99.0%. Seven empty shells remain unrepaired.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Sunny Isles Beach, FL** → `agent/scripts/fl/data_repair_fl_sunny_isles_beach.py` (1,999 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `smartgov_full` | 1,775 | Core SmartGov keys + `ProjectDescription` |
| `smartgov_no_desc` | 217 | Parcel Number present, no ProjectDescription |
| `smartgov_minimal` | 7 | No Parcel Number / ProjectDescription |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Build Status` (case-insensitive); sticky Inactive for `Expired*`; Closed date → Final; Issued date → Active |
| FILE_DATE | `My Project.Submitted` else `Created` |
| PERMIT_DATE | `My Project.Issued` else `Approved` |
| FINAL_DATE | `My Project.Closed` else approved Final/COO inspection (none present in sample) |

## Field assessments

### STATUS_NORMALIZED

| Build Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| CLOSED | 1,308 | Final (5 Active, 2 In Review, 1 null) | Fix non-Final → Final |
| Expired* | 230 | Inactive (169) / null (53) / Active (7) / In Review (1) | Fill/fix → Inactive |
| null | 221 | **null** | Infer from Closed/Issued/Submitted → Final/Active/In Review; 7 empty shells stay null |
| REVISED | 83 | **null** | Fill → Final (81 with Closed) or Active (2 Issued-only) |
| ACTIVE | 82 | Active (73) / In Review (5) / null (4) | Fix In Review/null → Active |
| RENEWED | 38 | Active | Closed stamp → Final (override) |
| READY TO ISSUE… / PENDING / PENDING REVIEW / IN REVIEW / review-ish | 9 / 7 / 4 / 3 / 3 | In Review (mostly) | Keep In Review unless Closed/Issued override |
| FINALED | 6 | Final | Correct |
| AWAITING CORRECTIONS… | 4 | **null** | Fill → In Review |
| APPROVED | 1 | Active | Correct |
| UNDER CLERICAL REVIEW | 1 | **null** | Fill → In Review |

**Root causes:**
1. Upstream mapper omitted `REVISED`, many null-`Build Status` shells, some `Expired*`, and a few review/ACTIVE labels → null `STATUS_NORMALIZED`.
2. Closed-date lifecycle not applied: `RENEWED` / `ACTIVE` / ready-to-issue rows with `My Project.Closed` stayed Active/In Review.
3. `Expired*` occasionally kept as Active/In Review instead of sticky Inactive.

**Repair performance:** FILLED 361, FIXED 56; missing 368 → 7.

### FILE_DATE

- Before: missing on **8 / 1,999**. All 1,991 present values matched `My Project.Submitted` (0 mismatches).
- 1 row (`AWAITING CORRECTIONS…`) had Submitted/Created but null `FILE_DATE` → FILLED.
- 7 empty shells have blank Submitted/Created → not fillable.

**Repair performance:** FILLED 1, FIXED 0; missing 8 → 7 (99.6% coverage).

### PERMIT_DATE

- Before: NaN on **205 / 1,999**. All 1,794 present values matched `My Project.Issued` (0 mismatches).
- 27 Active/Final rows had Issued/Approved available but missing `PERMIT_DATE` → FILLED (including upgrades of previously null-status shells).
- After repair: Active 168/168 (100%); Final 1,471/1,477 (99.6%). Remaining 6 gaps are CLOSED/null-BS shells with blank Issued and blank Approved.

**Repair performance:** FILLED 27, FIXED 0; missing 205 → 178.

### FINAL_DATE

- Before: NaN on **547 / 1,999**; Final had 1,289 / 1,306 present; 36 Active (mostly `RENEWED` with Closed) and 127 null-status rows carried Closed-backed finals.
- Status repair reclassifies those Closed-bearing Active/null rows to Final, so their dates are retained correctly rather than cleared.
- 10 Final rows missing `FINAL_DATE` despite a Closed stamp → FILLED; 1 CLOSED Final had `FINAL_DATE` 2023-10-19 vs Closed 2024-08-01 → FIXED.
- `Permit Inspections` is empty for every sample row, so FINALED / CLOSED shells with blank Closed cannot be filled from inspections (15 Final gaps remain).

**Repair performance:** FILLED 10, FIXED 1; missing 547 → 537. Final coverage 1,462 / 1,477 (99.0%).

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_sunny_isles_beach.py` (`data_repair`)
- Repaired parquet: `AGENT_DATA_PATH/repaired/permits_fl_sunny_isles_beach_repaired.parquet`
