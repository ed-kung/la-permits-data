# Lake Worth Beach (FL) data repair

Lake Worth Beach was the first `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing repair script. Its DATA JSON follows the same city-portal family as Tarpon Springs/Winter Garden/Oviedo (`permit_status` + `fees_detail`). FILE_DATE was already correct for every row. Main defects were null STATUS on fees-only rows, VOIDED/EXPIRED/CANCELLED apps mislabeled Final because permit status stayed CLOSED, PERMIT_DATE taken from the portal "Permit Date" stamp instead of "Issue Date" (861 PERMIT > FINAL inversions), and a smaller set of FINAL_DATE gaps/fixes from inspection history.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Lake Worth Beach, FL (2,000 sample rows)
- Script: `agent/scripts/fl/data_repair_fl_lake_worth_beach.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_lake_worth_beach_repaired.parquet`

## DATA schemas

| Schema | n | Contents |
| --- | ---: | --- |
| `permit_status` | 1,299 | `detail` / fees plus `permit_status_detail` + `insp_status_detail` |
| `fees_detail` | 701 | `detail` + fees only (Application Date / Application Status) |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,131; null 701; In Review 90; Active 69; Inactive 9.
- All 701 nulls were `fees_detail` rows (no `STATUS_ORIGINAL` / permit block).
- Canonical source: inactive Application Status (VOIDED / EXPIRED / CANCELLED / …) overrides; else `Status for Permit Number`; else `Application Status`.
- Upstream used `STATUS_ORIGINAL` ≈ permit status only, so VOIDED/EXPIRED/CANCELLED with CLOSED permit status were labeled Final (114 rows) → FIXED to Inactive.
- Other stale STATUS_ORIGINAL mislabels: CLOSED kept as Active (8); PERMIT PRINTED kept as In Review (8); FINAL INSPECTION COMPLETE kept as In Review (1); one Final → Active from PERMIT PRINTED.

### FILE_DATE

- Populated for all 2,000 rows; 100% match to `detail.Application Date`.
- No fill or fix needed.

### PERMIT_DATE

- Upstream used portal **Permit Date** (matches on 1,279 / 1,299 `permit_status` rows), not **Issue Date** (1,166 present).
- Permit Date is typically a later admin/closeout stamp (Issue < Permit Date on 1,098 of 1,166 dual-present rows), which produced 861 PERMIT_DATE > FINAL_DATE inversions before repair.
- In Review rows had spurious PERMIT_DATE from Permit Date (often with blank Issue Date) → cleared.
- Active/Final/Inactive with a real Issue Date are corrected to Issue Date; fees_detail and blank-Issue CLOSED rows cannot invent issuance.

### FINAL_DATE

- For Final rows, upstream mostly matched the latest successful inspection result date (same portal-family rule as Tarpon Springs/Winter Garden).
- Repair uses latest successful non-NOC inspection (APPROVED / APPROVED WITH EXCEPTION / PARTIALLY APPROVED / WAIVED), Final rows only; clears FINAL_DATE on non-Final.
- 717 Final rows still lack FINAL_DATE after repair (687 fees_detail + 24 empty `insp_status_detail` + 6 non-success-only) → not fillable from DATA.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 701 | 132 | 701 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 1,234 | 701 → 834 |
| FINAL_DATE | 12 | 22 | 1,001 → 1,005 |

STATUS after repair: Final 1,712; Inactive 133; In Review 85; Active 70; null 0.

STATUS transitions: null→Final 687; Final→Inactive 114; null→Inactive 10; Active→Final 8; In Review→Active 8; null→In Review 4; Final→Active 1; In Review→Final 1.

PERMIT_DATE FIXED = 1,101 replacements to Issue Date + 133 clears of unsupported Permit Date stamps (In Review; blank-Issue Closed; fees_detail). Missing rose from 701 → 834 because incorrect stamps were removed when Issue Date was absent.

FINAL_DATE FIXED = 6 value corrections + 16 clears on non-Final / unsupported stamps; 12 fills from inspection history on newly-Final or previously-empty Final rows.

After repair:

- FILE_DATE present for 100% of rows; equals Application Date on 2,000 / 2,000.
- PERMIT_DATE: Active 100%; Final 59.6% (1,021 / 1,712 — gap almost entirely fees_detail); In Review 0%; Inactive 56.4%.
- FINAL_DATE: Final 58.1% (995 / 1,712); cleared on non-Final.
- Among `permit_status` Final rows: PERMIT_DATE 1,021 / 1,025 (99.6%); FINAL_DATE 995 / 1,025 (97.1%).
- PERMIT_DATE equals Issue Date whenever both are present (0 mismatches / 1,166).
- Ordering: FILE_DATE > PERMIT_DATE on 0 rows; PERMIT_DATE > FINAL_DATE on 1 row (down from 861).

## Not repairable from DATA

- 691 Active/Final rows still missing PERMIT_DATE: 687 `fees_detail` Final (no Issue Date) + 4 `permit_status` CLOSED/ADMINISTRATIVELY CLOSED with blank Issue Date.
- 717 Final rows without a successful non-NOC inspection (or without an inspection block) → FINAL_DATE stays missing.
- In Review / Inactive fees_detail rows have no issuance or inspection history → PERMIT_DATE / FINAL_DATE stay missing.
