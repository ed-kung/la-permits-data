# Vista (CA) data repair

**Summary:** Assessed Vista's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_vista.py`. Vista uses a flat agency export with three key-naming variants of the same fields. All top-level date columns were null despite dates in DATA; the repair fills every FILE_DATE, fills PERMIT_DATE for all Active/Final rows, and fills FINAL_DATE for 99.1% of Final rows. It also fills 177 missing STATUS_NORMALIZED values (entire `flat_spaced` scrape plus BLUES/STOP shells). No previously populated statuses needed correction.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Vista, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `flat_mixed` | 1,599 | `PERMIT_STATUS`, `DATE_ENTERED`, `ParcelNo`, `Applicant`, … |
| `flat_upper` | 230 | Upper-case keys (`APPLICANT`, `PARCELNO`, `VALUATION`, …) |
| `flat_spaced` | 171 | Spaced keys (`PERMIT STATUS`, `DATE ENTERED`, `Parcel No`, …) |

Canonical mappings from DATA (after key normalization):

- `PERMIT_STATUS` → `STATUS_NORMALIZED`
- `DATE_ENTERED` → `FILE_DATE`
- `DATE_ISSUED` → `PERMIT_DATE`
- `DATE_FINALED` → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,386 / Inactive 251 / Active 186 / missing 177.

Issues:

1. **Missing (177):** All 171 `flat_spaced` rows (statuses never mapped into `STATUS_ORIGINAL` / `STATUS_NORMALIZED`), plus 5 `BLUES` and 1 `STOP` in `flat_mixed`.
2. **Incorrect:** None among already-populated rows. Existing values match `FINALED`/`FINAL`→Final, `ISSUED`/`APPROVED`→Active, `EXPIRED`/`VOID`/`CANCEL`→Inactive.

Status map used in repair: `FINALED`/`FINAL`→Final; `ISSUED`/`CD-ISSUED`/`APPROVED`/`BLUES`/`OPEN`/`CE-OPEN`→Active (OPEN/CE-OPEN without IssueDate → In Review; BLUES with DATE_FINALED → Final); `EXPIRED`/`VOID`/`CANCEL`/`CD-CANCEL`/`STOP`→Inactive; `CD-OPEN`/`PREAPP`→In Review.

Repair performance: **177 FILLED, 0 FIXED**; missing after: **0**.

After: Final 1,464 / Active 262 / Inactive 259 / In Review 15.

### FILE_DATE

Before: **2,000 / 2,000 missing**. Every DATA row has `DATE_ENTERED`.

Repair: **2,000 FILLED, 0 FIXED**. Coverage: **100%**.

### PERMIT_DATE

Before: **2,000 / 2,000 missing**. `DATE_ISSUED` is present for every Active/Final shell after status repair.

Repair: **1,726 FILLED, 0 FIXED** (Active 262 + Final 1,464). Remaining 274 missing are In Review (15) and Inactive (259), which are not expected to carry PERMIT_DATE.

Active coverage after repair: **262 / 262 (100%)**; Final: **1,464 / 1,464 (100%)**.

### FINAL_DATE

Before: **2,000 / 2,000 missing**. Most Final shells have `DATE_FINALED`; 13 FINAL/FINALED shells do not. Two VOID rows carry DATE_FINALED as a closure stamp (status stays Inactive; FINAL_DATE not filled). Two BLUES shells with DATE_FINALED were promoted to Final and received FINAL_DATE.

Repair: **1,451 FILLED, 0 FIXED**.

Final coverage after repair: **1,451 / 1,464 (99.1%)**. No spurious FINAL_DATE on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_vista.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 177 | 0 | 177 | 0 |
| FILE_DATE | 2,000 | 0 | 2,000 | 0 |
| PERMIT_DATE | 1,726 | 0 | 2,000 | 274 |
| FINAL_DATE | 1,451 | 0 | 2,000 | 549 |

Remaining gaps: 13 Final rows with null `DATE_FINALED` in DATA; PERMIT/FINAL missing counts on non-Active/Final statuses are expected.
