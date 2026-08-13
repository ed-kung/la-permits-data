# Gainesville (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Gainesville**. DATA is a municipal portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`; form-key variants for owner-builder / valuation extras). Upstream status mapping was mostly correct, but left 5 nulls (`Project Dox` / blank `Status:`) and kept 80 issued shells labeled In Review (`Under Review` / `On Hold` with Issue Date). `FILE_DATE` was missing on 1,040 rows and, when present, often equaled Issue Date (724) or a post-issue review date rather than application/intake. `PERMIT_DATE` already matched `Permit Details["Issue Date:"]` wherever both existed. `FINAL_DATE` was null for every row. The repair filled/fixed all statuses, corrected 509 `FILE_DATE` values (496 replacements + 13 post-issue clears) and filled 13, left `PERMIT_DATE` unchanged (already correct), and filled 374 Final `FINAL_DATE` values from passed Final* inspections. After repair: STATUS 100%; FILE_DATE 48.0%; Active/Final PERMIT_DATE 99.9%/99.6%; Final FINAL_DATE 75.9%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Gainesville, FL** → `agent/scripts/fl/data_repair_fl_gainesville.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share portal keys `Status:`, `Permit #:`, `Permit Details`, `Issue Date` (top-level always null), `Reviews`, `Inspections`. Form-key variants differ by permit type:

| Schema prefix | n | Notes |
| --- | ---: | --- |
| `portal_core_*` | 934 | Core keys only (≤16 top-level keys) |
| `portal_owner_builder_*` | 629 | Owner-builder affidavit / `Initials OB*` fields |
| `portal_extended_*` | 437 | Valuation / plan-review form extras |

Content suffixes (recoverable dates):

| Suffix | Meaning |
| --- | --- |
| `_issued_finaled` | Issue Date + passed Final* inspection |
| `_issued` | Issue Date only |
| `_applied` | Application/intake source, no Issue Date |
| `_status_only` | Status label only |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (Issue-date upgrade In Review→Active; blank/Project Dox inferred) |
| FILE_DATE | `Building Application Intake` Start; else `Date:AS` / `Date: AS:` on/before Issue; else earliest non-online Review Start/Completion on/before Issue |
| PERMIT_DATE | `Permit Details["Issue Date:"]` (top-level `Issue Date` always null) |
| FINAL_DATE | Latest passed Final* / certificate inspection date |

## Field assessments

### STATUS_NORMALIZED

| Status: | n | Upstream | Assessment |
| --- | ---: | --- | --- |
| Issued | 1,271 | Active | Correct |
| Closed | 492 | Final | Correct |
| Cancelled | 87 | Inactive | Correct |
| Under Review | 61 | In Review | **Incorrect when Issue Date present** → Active |
| Void | 31 | Inactive | Correct |
| On Hold | 25 | In Review | **19 with Issue Date** → Active; 6 remain In Review |
| Expired Permit / Expired | 22 / 5 | Inactive | Correct |
| Project Dox | 3 | **null** | Fill → Active (1 with Issue) / In Review (2) |
| (blank) | 2 | **null** | Fill → Active / Final from Issue / Final* insp |
| Online Application Received | 1 | In Review | Correct |

**Root causes:**
1. Upstream mapper omitted `Project Dox` and blank `Status:`.
2. Portal `Under Review` / `On Hold` often lags issuance; Issue Date is already populated on old shells.

**Repair performance:** FILLED 5, FIXED 80; missing 5 → 0.

### FILE_DATE

- Before: missing on **1,040 / 2,000**. Of 960 present values, **724** equaled Issue Date (not an application date). Many others matched Intake Completion or post-issue Online Message / Plan Review dates.
- Usable application sources: Intake Start (~720), `Date:AS` (often a post-issue affidavit stamp — used only when ≤ Issue), other early Review starts.
- Repair: FILLED 13; FIXED 509 (496 replaced with Intake Start / early review dates; 13 cleared when FILE post-dated Issue with no usable application source).
- After: missing **1,040 / 2,000** (48.0% coverage). Remaining gaps are older shells with empty Reviews and no `Date:AS`.
- Date-order after repair: `FILE_DATE > PERMIT_DATE` = 0.

**Repair performance:** FILLED 13, FIXED 509; ideal coverage still limited by missing agency application stamps.

### PERMIT_DATE

- Before: NaN on **78 / 2,000**. All 1,922 present values already matched `Permit Details["Issue Date:"]` (0 mismatches). Top-level `Issue Date` is always null.
- Active/Final gaps after status upgrades: 1 Issued + 2 Closed with blank Issue Date — not fillable.
- Remaining In Review rows (9) have no Issue Date; no spurious PERMIT clears needed.

**Repair performance:** FILLED 0, FIXED 0. Active coverage 99.9%; Final coverage 99.6%.

### FINAL_DATE

- Before: NaN on **2,000 / 2,000** (never populated upstream).
- Closed rows with a passed Final* inspection (Building/Plumbing/Roof/Electrical/… Final, including Approved-with-Comments): **374 / 493** Final after repair.
- 119 Closed shells lack a usable passed Final* inspection (empty Inspections, only non-final types, or non-pass statuses) → remain missing.
- No spurious FINAL_DATE on non-Final rows before or after.

**Repair performance:** FILLED 374, FIXED 0; Final coverage 75.9%.

## Artifacts

| Path | Description |
| --- | --- |
| `agent/scripts/fl/data_repair_fl_gainesville.py` | `data_repair()` implementation |
| `AGENT_DATA_PATH/gainesville_permits_repaired.parquet` | Repaired sample output |
