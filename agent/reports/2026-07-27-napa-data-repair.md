# Napa (CA) data repair

**Summary:** Napa was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the portal `DATA` JSON (`permit_info` + `inspections`). Status: **FIXED 42** (stale Active/In Review labels corrected from `PermitStatus` / `PermitFinaledDate`); 1 blank historical shell left missing. `FILE_DATE` already matched `PermitAppliedDate` for 1,998/2,000 rows (2 empty shells unrepaired). `PERMIT_DATE` missingness fell **122 → 114** (**FILLED 8**) via `PermitApprovedDate` when Issued was blank; Active/Final coverage is now **99.0% / 100%**. `FINAL_DATE` missingness fell **922 → 910** (**FILLED 13 · FIXED 1**): filled from `PermitFinaledDate` or approved final inspections after status upgrades, and cleared one spurious final on an Expired row. Remaining gaps are shells with no applied/issued/finaled dates and no usable final inspection.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Napa, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_napa.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/napa_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Sub-schemas reflect which `permit_info` dates are populated and whether `inspections` is non-empty:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_complete_insp` | 1,037 | Applied + Issued/Approved + Finaled; has inspections |
| `permit_info_issued_insp` | 640 | Applied + Issued/Approved; has inspections |
| `permit_info_issued` | 165 | Applied + Issued/Approved; no inspections |
| `permit_info_application` | 100 | Applied only |
| `permit_info_complete` | 49 | Applied + Issued/Approved + Finaled; no inspections |
| `permit_info_application_insp` | 5 | Applied only; has inspections |
| `permit_info_empty` / `_insp` | 4 | No usable `permit_info` dates |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus`; upgrade to Final when `PermitFinaledDate` set (unless inactive) |
| `FILE_DATE` | `permit_info.PermitAppliedDate` |
| `PERMIT_DATE` | `PermitIssuedDate`, else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`, else latest approved final / C of O inspection `Completed` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,054 · Active 434 · Inactive 405 · In Review 106 · missing 1

Issues (root cause: upstream often mirrored stale `STATUS_ORIGINAL` instead of current `PermitStatus` / finaled date):

1. **42 mis-normalized rows** relative to `DATA`:
   - ISSUED + `PermitFinaledDate` → Active (20) → Final
   - ISSUED W/COND + `PermitFinaledDate` → Active (12) → Final
   - FINALED → Active (8; `STATUS_ORIGINAL=issued`) → Final
   - ISSUED → In Review (1; `STATUS_ORIGINAL=under review`) → Active
   - EXPIRED → Active (1; `STATUS_ORIGINAL=issued`) → Inactive
2. **1 null status** — empty `PermitStatus` HISTORICAL RECORD shell with no dates; left missing.

When present, `PermitStatus` maps cleanly:

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, WORK COMPLETED | Final |
| ISSUED, ISSUED W/COND, APPROVED | Active |
| UNDER REVIEW, P, I, A, HOLD | In Review |
| EXPIRED, CANCELED, DENIED | Inactive |

Non-inactive rows with `PermitFinaledDate` are treated as Final even if the label still says ISSUED.

**After:** Final 1,094 · Inactive 406 · Active 394 · In Review 105 · missing 1  
Flags: **FILLED 0 · FIXED 42**

### FILE_DATE

**Before:** 2 missing (0.1%).

- 1,998/2,000 rows already equal `PermitAppliedDate` (calendar day).
- Gaps: `B1909-0091` (UNDER REVIEW shell, all dates blank) and `03 000 BP 104` (HISTORICAL RECORD shell). No alternate file-date source in `DATA`.

**After:** still 2 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 122 missing (6.1%). Among Active/Final: 11 / 1,488 missing.

Root cause: upstream preferred `PermitIssuedDate` only. Several Active/Final rows have blank Issued but a populated `PermitApprovedDate`.

Repairs (Active / Final only): fill from Issued, else Approved.

**After:** 114 missing. Active 390/394 (99.0%); Final 1,094/1,094 (100%).  
Flags: **FILLED 8 · FIXED 0**

Remaining Active gaps (4): ISSUED rows with both Issued and Approved blank (`EP2402-0004`, `E1508-0043`, `ADD2411-0001`, `M1309-0017`).

### FINAL_DATE

**Before:** 922 missing (46.1%). Among Final: 8 / 1,054 missing. Also 31 Active and 1 Inactive rows carried a `FINAL_DATE` (matching `PermitFinaledDate` / close timestamp).

Repairs:
1. After status upgrades, fill Final rows from `PermitFinaledDate` or approved final inspections (`**999 FINAL`, `199 Final Building`, `FINAL INSPECTION`, etc.; Result Approved / Approved w/cmts / blank).
2. Clear `FINAL_DATE` on non-Final rows (1 Expired close timestamp).

**After:** 910 missing. Final 1,090/1,094 (99.6%); Active/In Review/Inactive all 0%.  
Flags: **FILLED 13 · FIXED 1**

Remaining Final gaps (4): FINALED / WORK COMPLETED with blank `PermitFinaledDate` and no approved final inspection (`F1902-0002`, `EP1202-0036`, `EP1507-0049`, `B1302-0050` — last has only Corrections Req on final insp).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 0 | 42 | 1 → 1 |
| `FILE_DATE` | 0 | 0 | 2 → 2 |
| `PERMIT_DATE` | 8 | 0 | 122 → 114 |
| `FINAL_DATE` | 13 | 1 | 922 → 910 |
