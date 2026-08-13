# Winter Garden (FL) data repair

Winter Garden was the first `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing repair script. Its DATA JSON follows the same city-portal family as Oviedo/Lake Mary (`permit_status` + `fees_detail`). FILE_DATE was already correct; the main defects were null STATUS on fees-only rows, PERMIT_DATE taken from the portal "Permit Date" stamp instead of "Issue Date", and a small number of FINAL_DATE mismatches vs inspection history. The repair script fills/fixes these and writes flags plus `INFERRED_SCHEMA`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Winter Garden, FL (2,000 sample rows)
- Script: `agent/scripts/fl/data_repair_fl_winter_garden.py`
- Artifact: `AGENT_DATA_PATH/winter_garden_permits_repaired.parquet`

## DATA schemas

| Schema | n | Contents |
| --- | ---: | --- |
| `permit_status` | 1,936 | `detail` / fees plus `permit_status_detail` + `insp_status_detail` |
| `fees_detail` | 64 | `detail` + fees only (Application Date / Application Status) |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,784; Active 123; In Review 28; Inactive 1; **null 64**.
- All 64 nulls were `fees_detail` rows (no `Status for Permit Number`).
- Canonical source: prefer `Status for Permit Number`, else `Application Status`.
- Upstream status mapping was already correct for all `permit_status` rows (CLOSED / C.O. ISSUED / PERMIT PRINTED / PLAN CHECK / etc.).

### FILE_DATE

- Populated for all 2,000 rows; 100% match to `Application Date`.
- No fill or fix needed.

### PERMIT_DATE

- Upstream used portal **Permit Date** (1,884 rows), not **Issue Date**.
- Permit Date is typically a later admin/closeout stamp (Issue < Permit Date in 1,760 rows); it is not the issuance date.
- All 28 In Review rows had a spurious PERMIT_DATE from Permit Date while Issue Date was blank.
- Active/Final with a real Issue Date can be corrected; fees_detail and blank-Issue rows cannot.

### FINAL_DATE

- For Final rows, upstream mostly matched the latest successful non-NOC inspection (APPROVED / PARTIALLY APPROVED / etc.).
- 212 Final rows lacked a usable success inspection (184 empty `insp_status_detail`, 27 with only non-success results); not fillable from DATA.
- A few inspection rows have off-by-one-year schedule vs result stamps; repair prefers the later date in that case.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 63 | 0 | 64 → 1 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 1,885 | 64 → 133 |
| FINAL_DATE | 1 | 5 | 428 → 427 |

STATUS after repair: Final 1,799; Active 123; Inactive 47; In Review 30; null 1.

Null STATUS fills from Application Status: Inactive 46 (VOID / DENIED / CANCELLED / etc.), Final 15 (CLOSED / FINALED / CLOSED BY REPORT), In Review 2 (IN PLAN CHECK). One fees_detail row has blank Application Status and remains null.

PERMIT_DATE missing rose because incorrect Permit Date stamps were cleared when Issue Date was absent (In Review 28; Active 17; Final 24 permit_status + 15 fees_detail Final).

After repair:

- FILE_DATE present for 100% of rows with a status.
- PERMIT_DATE: Active 86.2%; Final 97.8%; In Review 0%; Inactive 1/47 (revoked, issued then revoked).
- FINAL_DATE: Final 87.4%; cleared on non-Final.
- PERMIT_DATE equals Issue Date whenever both are present (0 mismatches / 1,867).
- Ordering: FILE_DATE > PERMIT_DATE on 3 rows (source Application Date after Issue Date); PERMIT_DATE > FINAL_DATE on 1 row (inspection dated 2 days before issue).

## Not repairable from DATA

- 1 fees_detail row with empty Application Status → STATUS stays null.
- 56 Active/Final rows with no Issue Date in DATA → PERMIT_DATE stays missing.
- 226 Final rows without a successful non-NOC inspection → FINAL_DATE stays missing.
