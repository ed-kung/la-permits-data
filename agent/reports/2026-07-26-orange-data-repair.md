# Orange (CA) data repair

**Summary:** Orange was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the uniform `permit_info` / `search_data` `DATA` JSON. Status: **FIXED 125** — 119 `PO OPEN` (issued, still open) rows mislabeled In Review → Active; 3 `ISSUED`→In Review → Active; 1 `FINALED`→Active → Final; 2 stale `ISSUED` rows with a real `PermitFinaledDate` → Final. `FILE_DATE` already matched `PermitAppliedDate` wherever both exist (**FILLED 0 · FIXED 0**); 3 gaps remain with empty Applied. `PERMIT_DATE` **FILLED 3** for the newly Active `ISSUED` rows (Active now 100% populated; Final 99.8%). `FINAL_DATE` **FILLED 1** for the corrected Finaled row; Final now 99.9% populated. Remaining gaps are sparse legacy shells with no Issued/Approved/Finaled dates and no finaling inspections.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Orange, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_orange.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Sub-schemas reflect which `permit_info` dates are populated (optional `_insp` when `inspections` is non-empty):

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_complete_insp` | 768 | Applied + Issued + Finaled, with inspections |
| `permit_info_complete` | 744 | Applied + Issued + Finaled |
| `permit_info_issued` | 309 | Applied + Issued (no Finaled) |
| `permit_info_application` | 91 | Applied only |
| `permit_info_issued_insp` | 83 | Applied + Issued, with inspections |
| `permit_info_empty` / `_insp` | 4 | No usable permit_info dates |
| `permit_info_partial` | 1 | Dates present but Applied missing (or Applied+Finaled without issuance) |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (uppercased); ISSUED/APPROVED/PO OPEN with `PermitFinaledDate` → Final |
| `FILE_DATE` | `permit_info.PermitAppliedDate` |
| `PERMIT_DATE` | `PermitIssuedDate`, else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest finaling inspection `Completed` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,514 · In Review 200 · Active 181 · Inactive 105 · missing 0

`PermitStatus` maps cleanly after uppercasing (`Final`/`FINALED`/`FINALIZED`, `Issued`/`ISSUED`, `Expired`/`EXPIRED`/`expired`/`EXPIRE`, etc.). Issues:

1. **119 `PO OPEN` → In Review** — these are issued, still-open permits (`PermitIssuedDate` populated). Correct label is **Active**.
2. **3 `ISSUED` → In Review** — `STATUS_ORIGINAL` was `corrections`/`submitted` while portal status had already moved to ISSUED; also missing `PERMIT_DATE` despite Issued/Approved dates.
3. **1 `FINALED` → Active** — `STATUS_ORIGINAL` still `issued`; `PermitFinaledDate` present but `FINAL_DATE` null.
4. **2 `ISSUED` with `PermitFinaledDate`** — stale Active labels after finaling; upgraded to **Final**.

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, FINALIZED, Final, CLOSED | Final |
| ISSUED, Issued, APPROVED, PO OPEN | Active (→ Final if FinaledDate set) |
| SUBMITTED, PC OPEN, CORRECTIONS, UNDER REVIEW, HOLD | In Review |
| EXPIRED, Expired, expired, EXPIRE, CANCELLED, CANCEL, WITHDRAWN | Inactive |

**After:** Final 1,517 · Active 300 · In Review 78 · Inactive 105 · missing 0  
Flags: **FILLED 0 · FIXED 125**

### FILE_DATE

**Before:** 3 missing (0.15%).

- When both present, `FILE_DATE` always equals `PermitAppliedDate` (calendar day).
- The 3 gaps have empty `PermitAppliedDate` (CANCELLED shell, UNDER REVIEW shell, and one 1999 Final with Issued/Finaled only). Fee `Paid Date` is not used as an application proxy.

**After:** still 3 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 99 missing (4.95%). Among Active/Final: 3 / 1,695 missing (all Final with empty Issued and Approved).

Upstream already matched `PERMIT_DATE` to `PermitIssuedDate` whenever Issued was present. Gaps:

1. Three `ISSUED` rows mislabeled In Review had Issued (and sometimes Approved) but null `PERMIT_DATE` → **FILLED** after status → Active.
2. Three Final `FINALED` rows have neither Issued nor Approved (application + finaled only, or admin replacement record) → not repairable.

**After:** 96 missing (4.8%). Active 100% · Final 99.8%.  
Flags: **FILLED 3 · FIXED 0**

### FINAL_DATE

**Before:** 486 missing overall; among Final: 2 / 1,514 missing. Two Active `ISSUED` rows incorrectly carried `FINAL_DATE` matching `PermitFinaledDate` (stale status).

Repairs:
1. Upgrade those 2 stale ISSUED (+ the 1 FINALED→Active) to Final; keep / fill FinaledDate.
2. Fill Final rows from `PermitFinaledDate`, else finaling inspection `Completed` (`Result` FINAL/FINALED or `Type` containing FINAL).
3. Clear `FINAL_DATE` when effective status is not Final (none remained after status upgrades).

**After:** 485 missing overall. Final 99.9% populated · Active/In Review/Inactive 0%.  
Flags: **FILLED 1 · FIXED 0**

Not repairable: 2 Final rows (`FINALED` admin replacement with no FinaledDate/inspections; `CLOSED` 1989 with no FinaledDate/inspections).

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 125 | 0 | 0 |
| FILE_DATE | 0 | 0 | 3 | 3 |
| PERMIT_DATE | 3 | 0 | 99 | 96 |
| FINAL_DATE | 1 | 0 | 486 | 485 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_orange.py`
