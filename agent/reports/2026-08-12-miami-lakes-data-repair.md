# Miami Lakes (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Miami Lakes**. DATA is a uniform civic/eTRAKiT payload (`permit_info` + dict-format `inspections`; `search_data` with/without `FOLIO`). Upstream left 95 `STATUS_NORMALIZED` nulls (mostly unmapped `NULL/VOID`) and mislabeled several `FINALED` / `ISSUED` / `DENIED` / `EXPIRED` / `READY` / `NULL/VOID` / `RENEWED` rows. Present non-null dates already matched `PermitAppliedDate` / `PermitIssuedDate` / `PermitFinaledDate` except two stale `PERMIT_DATE` values. The repair filled 94 statuses and 3 `FILE_DATE` values, filled/fixed 58 `PERMIT_DATE` values, filled 20 `FINAL_DATE` values (including 18 from passed final inspections), and cleared 23 spurious Inactive finals. After repair: STATUS 99.9% populated; FILE_DATE 100%; Active/Final PERMIT_DATE 99.0%/96.1%; Final FINAL_DATE 94.8%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Miami Lakes, FL** → `agent/scripts/fl/data_repair_fl_miami_lakes.py` (1,999 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level keys: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. `search_data` appears in two key-set variants (with / without `FOLIO`), but canonical lifecycle fields always live under `permit_info`. Content variants split by which `permit_info` dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `civic_issued_finaled` | 1,484 | Issued + finaled dates |
| `civic_issued` | 251 | Issued, no finaled |
| `civic_applied` | 148 | Applied only |
| `civic_finaled` | 95 | Finaled without issued |
| `civic_approved` | 21 | Approved (no issued/finaled) |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (+ Final when `PermitFinaledDate` set, except Inactive terminals; In Review labels with issued → Active) |
| FILE_DATE | `PermitAppliedDate` else `PermitIssuedDate` |
| PERMIT_DATE | `PermitIssuedDate` else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` else latest passed FINAL/CO/CC inspection |

## Field assessments

### STATUS_NORMALIZED

| PermitStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| FINALED | 1,610 | Final (3 mislabeled) | 3 → Final |
| NULL/VOID | 101 | **null** (92) / In Review (7) / Inactive (2) | → Inactive |
| ISSUED | 96 | Active (88); In Review (5); Inactive (2); null (1) | → Active (2 with finaled → Final) |
| EXPIRED | 61 | Inactive (1 Active) | → Inactive |
| CANCELLED | 22 | Inactive | Correct |
| ON REVIEW | 18 | In Review (1 with issued) | Issued row → Active |
| CLOSED | 18 | Final | Correct |
| DENIED | 16 | Inactive (1 In Review) | → Inactive |
| CO ISSUED | 16 | Final | Correct |
| READY | 13 | In Review (1 Inactive; 1 with issued) | Issued → Active; Inactive → In Review |
| RENEWED | 8 | Active (all carry `PermitFinaledDate`) | → Final |
| EXPIRED APPLICATION | 8 | Inactive | Correct |
| CC ISSUED | 5 | Final | Correct |
| CERTIFIED | 2 | Final | Correct |
| PENDING | 1 | In Review | Correct |
| VOID | 1 | Inactive | Correct |
| TCC ISSUED | 1 | Active | Correct |
| REQUIRED | 1 | **null** | Fill → In Review |
| (blank) | 1 | **null** | No strong signal → leave null |

**Root causes:**
1. Upstream mapper omitted `NULL/VOID` and `REQUIRED`, leaving 93 nulls (plus 1 blank shell).
2. `STATUS_ORIGINAL` sometimes disagreed with live `PermitStatus` (e.g. ISSUED rows still labeled ready / null/void / pending), producing In Review / Inactive / null labels on issued permits.
3. `RENEWED` (and a few `ISSUED`) shells still carry `PermitFinaledDate` but kept an Active / In Review label.
4. One-off mislabels: `DENIED`→In Review, `EXPIRED`→Active, `READY`→Inactive, `FINALED`→Active/In Review/Inactive.

**Repair performance:** FILLED 94, FIXED 31; missing 95 → 1 (blank PermitStatus shell only).

### FILE_DATE

- Before: missing on **3 / 1,999**. Present values always matched `PermitAppliedDate` at calendar-day resolution (0 mismatches).
- All 3 gaps are `FINALED` shells with blank `PermitAppliedDate` but a usable `PermitIssuedDate` → filled from issued.
- Ideal coverage after repair: 100% for every status class.

**Repair performance:** FILLED 3, FIXED 0; missing 3 → 0 (100% coverage).

### PERMIT_DATE

- Before: missing on **270 / 1,999**; present values matched `PermitIssuedDate` except **2** stale values (stored 2006-03-15 / 2020-06-08 while DATA shows 2024 re-issue dates).
- Filled 56 from `PermitIssuedDate` or `PermitApprovedDate` (Final 45, Active 7, Inactive 4 after status repair).
- Fixed 2 stale Active `PERMIT_DATE` values to match `PermitIssuedDate`.
- Remaining Active/Final gaps (65): `FINALED` (51), `CLOSED` (12), `RENEWED` (1), `TCC ISSUED` (1) with neither issued nor approved in DATA.
- In Review rows correctly have no `PERMIT_DATE` after repair (spurious values cleared via status upgrades to Active).

**Repair performance:** FILLED 56, FIXED 2; missing 270 → 214. Active coverage 99.0%; Final coverage 96.1%.

### FINAL_DATE

- Before: missing on **422 / 1,999**, including Final gaps; 10 Active and 9 Inactive rows incorrectly carried `PermitFinaledDate`, plus 14 null-status `NULL/VOID` rows with a final stamp.
- Filled 20 Final gaps: 2 from `PermitFinaledDate`, 18 from passed FINAL / CO / CC inspections when `PermitFinaledDate` was blank.
- Cleared 23 spurious Inactive finals (FIXED). Active+finaled rows (mostly `RENEWED`) were upgraded to Final so their dates were retained rather than cleared.
- Remaining Final gaps (87): `FINALED` (64), `CLOSED` (15), `CO ISSUED` (4), `CC ISSUED` (3), `CERTIFIED` (1) with no finaled stamp and no usable passed final inspection.

**Repair performance:** FILLED 20, FIXED 23; overall missing 422 → 425 (fills offset by Inactive clears), but Final coverage is 94.8% (1,574 / 1,661) with 0% FINAL_DATE on Active / In Review / Inactive.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_miami_lakes.py`
- Entry point: `data_repair(df)`
- Outputs: overwritten `STATUS_NORMALIZED` / `FILE_DATE` / `PERMIT_DATE` / `FINAL_DATE`; flags `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`}; `INFERRED_SCHEMA`
- Conventions follow `agent/scripts/ny/data_repair_ny_ny.py` and the civic pattern in `agent/scripts/fl/data_repair_fl_okeechobee_county.py`

## Artifacts

- Repaired sample parquet: `AGENT_DATA_PATH/miami_lakes_repaired_sample.parquet`
