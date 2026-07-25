# San Francisco (CA) data repair — 2026-07-24

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for San Francisco (first CA-sample jurisdiction lacking a repair script after LA / San Diego / Oakland / San Jose). Wrote `agent/scripts/data_repair_ca_san_francisco.py`. On the 2,001-row sample: 5 status fills + 513 status fixes; 270 file-date fills; 4 permit fills + 1 permit fix; 7 final fills + 2 final fixes. After repair: FILE_DATE 100%, Active/Final PERMIT_DATE ≈100%, Final FINAL_DATE 100%, with no spurious finals on non-Final rows.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in `permits_ca_sample.parquet` first-appearance order. Los Angeles, San Diego, Oakland, and San Jose already had repair scripts. **San Francisco (CA)** was the first without `agent/scripts/data_repair_ca_san_francisco.py`.

## DATA schema

SF DBI permit-portal scrape. Every row has `processing_status` (`[{date, stage, comments}, ...]`). Two sub-schemas:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `with_detail` | 1,489 | Also has `agents` / `inspections` / `addenda_details`; stages ordered **chronologically** |
| `header_only` | 512 | Header fields only; stages ordered **reverse-chronologically** |

Useful fields:
- Status: chronologically latest `processing_status.stage` (not array position)
- File date: `FILED` / `FILING` / `TRIAGE` (else earliest stage date)
- Permit date: earliest `ISSUED` (else `APPROVED`)
- Final date: latest `COMPLETE` (else final inspection approved)

## Field assessment

### STATUS_NORMALIZED

Before: Final 854, Active 748, In Review 331, Inactive 63; **5 missing** (`triage`).

Root cause: the upstream pipeline set `STATUS_ORIGINAL` from the **last array element** of `processing_status`. On `header_only` rows that element is the *earliest* stage (e.g. `FILED` / `ISSUED`), so completed and expired permits were mislabeled In Review / Active.

Repairs (by calendar date):
- **5 FILLED**: `triage` → In Review
- **513 FIXED**, mainly:
  - COMPLETE → Final (212 Active + 187 In Review)
  - EXPIRED → Inactive (51 Active + 52 In Review)
  - ISSUED → Active (11 In Review)
  - plus hard cancels / withdrawn

Special case: **COMPLETE beats later Auto-expire EXPIRED** (2 rows finaled then auto-expired ~1 year later). Hard cancels (`CANCELLED` / `WITHDRAWN` / `REVOKED` / `DISAPPROVED`) still win when chronologically latest.

After: Final 1,253, Active 496, Inactive 166, In Review 86; **0 missing**.

### FILE_DATE

270 missing (13.5%). Where populated and a `FILED` stage exists, FILE_DATE already matched (1,731/1,731).

- **270 FILLED**: 7 `with_detail` triage-only stubs from `TRIAGE`; 263 `header_only` rows with no `FILED`/`FILING`/`TRIAGE` filled from earliest stage date (almost always `ISSUED`) as an application-date proxy.
- No incorrect non-missing FILE_DATE values found.

After: **0 missing** (100% coverage). Note: header_only FILE fills often equal PERMIT_DATE because issuance is the only dated stage available.

### PERMIT_DATE

118 missing. Ideal: populated for Active and Final.

- Existing values already matched earliest `ISSUED` on nearly all rows.
- **4 FILLED** on Active/Final from `ISSUED` / `APPROVED`.
- **1 FIXED**: dual-issuance row had the later re-issue date; canonicalized to first `ISSUED`.
- **1 Final** remains without PERMIT_DATE: `COMPLETE` with no `ISSUED`/`APPROVED` in DATA.
- Inactive may retain PERMIT_DATE (issued then expired/cancelled). In Review has none after repair.

After repair, PERMIT_DATE coverage: Active **100%**, Final **99.9%**.

### FINAL_DATE

755 missing. Ideal: populated for Final only.

Before repair, 205 Active and 187 In Review rows had FINAL_DATE — all were status-mislabeled completes on `header_only` (array-order bug). After status correction they become Final and keep their dates.

- **7 FILLED** on Final rows with `COMPLETE` but blank FINAL_DATE (including 7 Active→Final with_detail completes).
- **2 FIXED** to the *latest* `COMPLETE` when multiple complete stamps existed.
- Spurious finals on non-Final cleared as part of status-driven logic (none remain).

After repair, FINAL_DATE coverage on Final: **100%** (0% on Active / In Review / Inactive).

## Why some records stay incomplete

1. **1 Final without ISSUED/APPROVED** — completed without an issuance stage in DATA; PERMIT_DATE cannot be recovered.
2. **Inactive without ISSUED** — cancelled/withdrawn/disapproved before issuance; PERMIT_DATE correctly absent.
3. **header_only FILE_DATE proxy** — true application date unavailable; filled from `ISSUED` so FILE_DATE often equals PERMIT_DATE.

## Repair performance (n=2,001)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 5 | 513 | 5 → 0 |
| FILE_DATE | 270 | 0 | 270 → 0 |
| PERMIT_DATE | 4 | 1 | 118 → 114 |
| FINAL_DATE | 7 | 2 | 755 → 748 |

748 remaining FINAL_DATE missings are non-Final rows (correctly empty).

## Artifacts

- Script: `agent/scripts/data_repair_ca_san_francisco.py`
- Function: `data_repair(df)` → adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` columns (`FILLED` / `FIXED`)
