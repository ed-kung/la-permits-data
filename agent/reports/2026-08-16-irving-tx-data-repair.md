# Irving (TX) data repair

**Summary:** Irving was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,001 rows share one portal schema (`permit_info` / one blank-status `permit_info_unstated`). STATUS_NORMALIZED was missing on 43 rows (NONE, PENDING INSPECT, blank) and is now fully filled; FILE_DATE is now complete via Issued fallback on legacy NONE rows; PERMIT_DATE gained 23 Approved-date fills; FINAL_DATE gained 34 inspection fills and 4 spurious non-Final finals were cleared.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Irving, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` after existing TX repairs through Lubbock)
- Script: `agent/scripts/tx/data_repair_tx_irving.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_irving_repaired.parquet`

## DATA schema

Every record has top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`.

| INFERRED_SCHEMA | n |
| --- | ---: |
| permit_info | 2,000 |
| permit_info_unstated | 1 |

Canonical source fields in `permit_info`:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | PermitStatus | Finaled / Issued / Approved dates when status blank |
| FILE_DATE | PermitAppliedDate | PermitIssuedDate (legacy NONE rows) |
| PERMIT_DATE | PermitIssuedDate | PermitApprovedDate |
| FINAL_DATE | PermitFinaledDate | latest approved/pass inspection `Completed` |

## Field assessment

### STATUS_NORMALIZED

Prior distribution: Final 1,698 · Inactive 158 · Active 86 · missing 43 · In Review 16.

Existing mappings were already correct for mapped statuses (FINALED/CLOSED/… → Final, ISSUED → Active, PAID/HOLD/… → In Review, CANCELLED/EXPIRED/VOID/DENIED → Inactive). The 43 nulls were unmapped / blank:

| PermitStatus | n | Repair mapping |
| --- | ---: | --- |
| NONE | 37 | Active (legacy PARENT cases with Issued, blank Applied) |
| PENDING INSPECT | 5 | Active (CO / post-approval under inspection) |
| (blank) | 1 | Final (inferred from PermitFinaledDate) |

After repair: Final 1,699 · Active 128 · Inactive 158 · In Review 16 · missing 0.

### FILE_DATE

- When present (1,964), always matched `PermitAppliedDate` at day resolution.
- 37 missing — all legacy `NONE` PARENT rows with blank Applied; recoverable from `PermitIssuedDate` (same day as existing PERMIT_DATE / fee Paid Date).
- After repair: 2,001 / 2,001 populated.

### PERMIT_DATE

- When present with Issued (1,899), always matched `PermitIssuedDate`.
- 102 missing before; 23 had blank Issued but usable `PermitApprovedDate` → FILLED.
- Remaining 79 gaps have neither Issued nor Approved in DATA (17 Final, 3 Active, plus In Review / Inactive where PERMIT is optional).

### FINAL_DATE

- When present with Finaled (1,544), always matched `PermitFinaledDate`.
- 159 Final rows missing FINAL_DATE with blank FinaledDate; 34 recoverable from approved/pass inspection completion dates (`APPROVED/PASS`, `APPROVED WITH EXCEPT`, rare `APPROVEDA/PASS`); 125 remain without a date source — mostly `NO INSP REQUESTED`, `NO FINAL REQ -CLOSED`, and some `CLOSED` with empty / non-approved inspections.
- 4 incorrect values on non-Final rows (3 PAID / In Review, 1 CANCELLED / Inactive) carried `PermitFinaledDate` → cleared (FIXED).
- After status fill, the blank-status Final row keeps its Finaled date.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 43 | 0 | 43 → 0 |
| FILE_DATE | 37 | 0 | 37 → 0 |
| PERMIT_DATE | 23 | 0 | 102 → 79 |
| FINAL_DATE | 34 | 4 | 457 → 427 |

After repair, by status:

- **FILE_DATE:** 2,001 / 2,001 (100%)
- **PERMIT_DATE:** Active 125/128 (97.7%), Final 1,682/1,699 (99.0%)
- **FINAL_DATE:** Final 1,574/1,699 (92.6%); non-Final all clear (0%)

## Not repairable

- 20 Active/Final rows with no Issued or Approved date in DATA (3 Active + 17 Final).
- 125 Final rows with neither FinaledDate nor approved/pass inspection Completed dates (often statuses that explicitly skip final inspection).
