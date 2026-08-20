# La Porte (TX) data repair

**Summary:** La Porte was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (1,999 rows). DATA has two schemas (`permit_full` / `application_only`). STATUS_NORMALIZED was missing on 109 rows and wrong on 5 (stale `STATUS_ORIGINAL`); all are now populated from `Status for Permit Number` or `Application Status`. FILE_DATE already matched `Application Date` on every row. PERMIT_DATE was corrected from the portal’s later `Permit Date` stamp to true `Issue Date` (998 FIXED + 8 FILLED). FINAL_DATE was filled/fixed from the last APPROVED inspection date where available; ~436 Final rows still lack a final timestamp because CLOSED records often have empty inspection lists.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sample order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover prior cities through Richardson. **La Porte** was the first missing pair → `agent/scripts/tx/data_repair_tx_la_porte.py`.

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `permit_full` | 1,898 | `detail` + `permit_status` / `permit_status_detail` + `insp_status` / `insp_status_detail` (+ fees) |
| `application_only` | 101 | `detail` + fees only (no permit / inspection block) |

Canonical sources:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `permit_status_detail['Status for Permit Number']` (`permit_full`) | `detail['Application Status']` (`application_only`) |
| FILE_DATE | `detail['Application Date']` | `permit_status_detail['Application Date']` |
| PERMIT_DATE | `permit_status_detail['Issue Date']` | `Permit Date` |
| FINAL_DATE | last APPROVED row in `insp_status_detail` (date col index 3, else 1) | — |

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,022 / Active 830 / In Review 26 / Inactive 12 / missing 109.

Missing rows were almost all `application_only` (101) plus 8 `permit_full` rows with null `STATUS_ORIGINAL` despite `Status for Permit Number = PERMIT PRINTED`.

Five `permit_full` mismatches vs permit status (upstream used stale `STATUS_ORIGINAL`):

| Status for Permit Number | Before | After | n |
| --- | --- | --- | ---: |
| C.O. ISSUED | Active | Final | 1 |
| FINAL INSPECTION COMPLETE | Active | Final | 2 |
| PERMIT PRINTED | In Review | Active | 2 |

Application-only fills used `Application Status` (e.g. `PLAN REVIEW PROCESS` → In Review, `APPL. IS VOIDED/DELETED` → Inactive, `ADMIN. PERMIT CLOSED` → Final).

After: Final 1,042 / Active 837 / In Review 68 / Inactive 52 / missing 0.

### FILE_DATE

Fully populated before repair (0 missing). Every row matched `detail['Application Date']` at calendar-day resolution. No FILLED/FIXED changes.

### PERMIT_DATE

Before: missing on all 109 null-status rows; Active/Final already had PERMIT_DATE.

Upstream PERMIT_DATE almost always equaled `Permit Date`, not `Issue Date`. For Final rows those two often diverge: `Permit Date` is a later portal update that frequently falls *after* final inspection (387 pre-existing PERMIT>FINAL order violations). `Issue Date` is the issuance stamp and nearly eliminates that problem.

Repair prefers `Issue Date`, falls back to `Permit Date` when Issue is blank. After repair: Active 837/837 (100%), Final 1,025/1,042 (98.4%). The 17 Final gaps are `application_only` rows with no permit block.

### FINAL_DATE

Before: present on 599/1,022 Final rows; absent on all non-Final.

When present, FINAL_DATE matched the last APPROVED inspection’s 4th-column date on ~588/599 rows. Repair fills missing Final rows from that rule and corrects the ~11 mismatches.

After: Final 606/1,042 (58.2%); non-Final cleared to null. Remaining Final gaps are almost all `CLOSED` / `ADMIN. PERMIT CLOSED` with empty (or non-APPROVED) `insp_status_detail` — no final/CO timestamp elsewhere in DATA.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 109 | 5 | 109 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 8 | 998 | 109 → 101 |
| FINAL_DATE | 7 | 11 | 1,400 → 1,393 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 100%, Final 98.4%
- **FINAL_DATE:** Final 58.2%; non-Final 0%

Date-order violations after repair: FILE>PERMIT=1, PERMIT>FINAL=9, FILE>FINAL=3 (down from PERMIT>FINAL=387 before).

## Not repairable

- 17 Final `application_only` rows have no `Issue Date` / `Permit Date` → PERMIT_DATE stays missing.
- ~436 Final rows (mostly CLOSED with empty inspection lists) have no finaling timestamp → FINAL_DATE stays missing.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_la_porte.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_la_porte_repaired.parquet`
