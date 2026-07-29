# Buena Park (CA) data repair — 2026-07-28

Buena Park was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. CitizenServe `main`/`extra`/`location` JSON has complete `FILE_DATE` (from `dateCreated`) and `STATUS_NORMALIZED` that matches `main.status` 1:1, but form `Status` / `Date Finaled` / `Date Issued` often contradict that code, `FILE_DATE` lags `dateSubmitted` on 23 rows, and `PERMIT_DATE` / `FINAL_DATE` are empty on all 2,000 rows. Repair fixes 99 statuses and 23 file dates, and fills 599 permit dates and 296 final dates from `extra` ASI-style fields.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Buena Park, CA** → `agent/scripts/ca/data_repair_ca_buena_park.py` (n=2,000).

## DATA schema

All rows share CitizenServe top-level keys (`main`, `extra`, `location`). `main.status` codes map to `STATUS_ORIGINAL` (`0=draft`, `1=active`, `2=complete`, `-1=stopped`). Building / trade forms often carry named `Status`, `Date Applied`, `Date Issued`, and `Date Finaled` under `extra`; CE, planning, and many modern shells do not. Variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `citizenserve_form_other` | 1,279 | Extra form fields without Status / Applied / Issued / Finaled dates (mostly CE, planning inquiries) |
| `citizenserve_issued_dates` | 307 | Parseable `Date Issued`, no `Date Finaled` |
| `citizenserve_finaled_dates` | 296 | Parseable `Date Finaled` |
| `citizenserve_status_form` | 107 | `Status` and/or `Date Applied` only |
| `citizenserve_empty_extra` | 11 | Empty `extra` dict |

## Field assessment

### STATUS_NORMALIZED

- Missing on 0 / 2,000. Upstream map from `STATUS_ORIGINAL` / `main.status` is internally consistent (Final 1,083 · In Review 490 · Active 394 · Inactive 33).
- When `extra['Status']` or dates are present, that code often lags the form:
  - `FINALED` + `Date Finaled` left Active (9) → should be Final.
  - `PLAN CHECK` / `DUE` / `APPLIED` / `PAID` / `INVEST` left Active without an issued date (64) → In Review.
  - `EXPIRED` / `CANCELED` / `VOID` left Active or Final (12) → Inactive.
  - `ISSUED` / `APPROVED` left Final with no `Date Finaled` (12) → Active.
  - `ISSUED` (or bare `Date Issued`) left In Review (2) → Active.
- Root cause: normalization keyed only off `main.status` / `STATUS_ORIGINAL`, ignoring form `Status` and finaling/issuance dates.
- **Repair:** refine `main.status` with `extra['Status']` and date evidence (Date Finaled / FINALED → Final; terminal Inactive labels override; Issued demotes stale Final shells; in-review labels demote Active only when no Date Issued) → **0 FILLED**, **99 FIXED**. Missing after: 0.

Status transitions: Active→In Review 64; Final→Active 12; Active→Final 9; Active→Inactive 9; Final→Inactive 3; In Review→Active 2.

### FILE_DATE

- Present on 2,000 / 2,000. Every value matched `main.dateCreated` (UTC date).
- **Issue:** 23 rows have `dateSubmitted` on a later calendar day than `dateCreated`; application/submittal date should prefer submitted.
- **Repair:** prefer `dateSubmitted`, else `dateCreated`, else `Date Applied` → **0 FILLED**, **23 FIXED**. Coverage remains 100%.

### PERMIT_DATE

- Missing on 2,000 / 2,000 (100%). No previously populated values to validate.
- Recoverable source: `extra['Date Issued']` (600 non-empty parseable values). One FINALED row has `Date Issued` after `Date Finaled`; that issued stamp is skipped as unreliable.
- **Repair:** **599 FILLED**, **0 FIXED**. Missing after: 1,401.
- Post-repair Active PERMIT coverage: 124/326 (38.0%); Final: 443/1,077 (41.1%). Remaining gaps are mostly CE/planning/`citizenserve_form_other` shells with no issuance field. Inactive retains 32 issued dates (expired/canceled permits that had been issued).

### FINAL_DATE

- Missing on 2,000 / 2,000 (100%).
- Recoverable source: `extra['Date Finaled']` on rows whose effective status is Final (296).
- **Repair:** **296 FILLED**, **0 FIXED**. Missing after: 1,704.
- Post-repair Final FINAL coverage: 296/1,077 (27.5%). No FINAL_DATE written on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 99 | 0 | 0 |
| FILE_DATE | 0 | 23 | 0 | 0 |
| PERMIT_DATE | 599 | 0 | 2,000 | 1,401 |
| FINAL_DATE | 296 | 0 | 2,000 | 1,704 |

Status distribution after repair: Final 1,077 · In Review 552 · Active 326 · Inactive 45.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 326 | 100% | 38.0% | 0% |
| Final | 1,077 | 100% | 41.1% | 27.5% |
| In Review | 552 | 100% | 0% | 0% |
| Inactive | 45 | 100% | 71.1% | 0% |

Overall FILE_DATE coverage: 2,000 / 2,000 (100%). Active+Final PERMIT_DATE: 567 / 1,403 (40.4%). Final FINAL_DATE: 296 / 1,077 (27.5%).

Chronology after repair: `FINAL_DATE < PERMIT_DATE` = 0. `PERMIT_DATE < FILE_DATE` = 69 (60 Parking Citations where citation `Date Issued` precedes portal create/submit by ~1 day; 9 building/trade rows where local `Date Applied`/`Date Issued` is one calendar day before UTC `dateSubmitted`). `FINAL_DATE < FILE_DATE` = 1 (the inverted Issued/Finaled Roof Permit; PERMIT skipped, FINAL kept).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_buena_park.py` (`data_repair` entry point)
- No derived datasets written under `AGENT_DATA_PATH`
