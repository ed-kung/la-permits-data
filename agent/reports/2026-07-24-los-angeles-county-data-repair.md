# Los Angeles County CA data repair

**Summary:** Los Angeles County’s 1,999 sample records are Tyler EnerGov payloads (`entity` / `details` / `fees`, with an optional reviews bundle). Upstream `FILE_DATE` is complete and matches `ApplyDate`. The main defects are stale `STATUS_ORIGINAL` labels vs `entity.CaseStatus` (33 rows), missing `PERMIT_DATE`/`FINAL_DATE` on remapped Issued/Finaled rows, and 28 non-Final rows with spurious `FINAL_DATE`. After repair: Active and Final have 100% `FILE_DATE` / ideal-status date coverage except 22 Finaled rows with no `IssueDate` in DATA. Script: `agent/scripts/data_repair_ca_los_angeles_county.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Los Angeles County"`, `STATE == "CA"` |
| N | 1,999 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Los Angeles County, CA (after Alhambra … Los Angeles) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,795 |
| `entity_fees_reviews` | 203 |
| `entity_basic` | 1 |

Canonical fields under `entity` (`details` as fallback; `CaseStatus` and `PermitStatus` agree on every sample row):

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate` |
| `FINAL_DATE` | `entity.FinalDate` (fallback `details.FinalizeDate`, Final status only) |

`ExpireDate` is a validity window, not a completion date. `FinalDate` / `FinalizeDate` are identical when present (1,023 rows).

Status map: Finaled → Final; Issued → Active; Expired / Void / Canceled / Denied → Inactive; In Review / Waiting for Applicant / New - Online / On Hold / Approved Ready for Permit / Approved Pending Clearances / New / Exempt → In Review.

## Field assessment

### STATUS_NORMALIZED — 0 missing; 33 incorrect

Upstream mapped `STATUS_ORIGINAL` (lowercased portal label) → normalized status. That label disagrees with `entity.CaseStatus` on 33 rows (portal label stale after later status transitions):

| CaseStatus | Was | Should be | n | Flag |
| --- | --- | --- | --- | --- |
| Finaled | Active (`STATUS_ORIGINAL` = issued) | Final | 23 | FIXED |
| Expired | Active (`STATUS_ORIGINAL` = issued) | Inactive | 8 | FIXED |
| Issued | In Review (`STATUS_ORIGINAL` = new - online) | Active | 1 | FIXED |
| Issued | In Review (`STATUS_ORIGINAL` = approved ready for permit) | Active | 1 | FIXED |

All other CaseStatus values already map to the correct `STATUS_NORMALIZED`. After repair: Final 995, Active 490, In Review 281, Inactive 233 (**0 missing**).

### FILE_DATE — complete and correct

- Ideal: application / submittal date for all records.
- 1,999 / 1,999 match the UTC calendar day of `entity.ApplyDate` (0 mismatches, 0 missing).
- No FILLED / FIXED.

### PERMIT_DATE — correct when present; 2 fillable after status fix

- Ideal: populated for Active and Final.
- Where both `PERMIT_DATE` and `IssueDate` exist, UTC day always matches (0 mismatches).
- Pre-repair Active 519/519 complete; Final 950/972 missing IssueDate as well as `PERMIT_DATE`.
- The two Issued→Active remaps had `IssueDate` and null `PERMIT_DATE` → **FILLED 2**.
- **Not fillable:** 22 `CaseStatus=Finaled` rows have `IssueDate` null and `details.Issued=False`, with no alternate issuance timestamp in DATA → left missing.

After repair: Active 490/490 (100%), Final 973/995 (97.8%). Remaining missing Active/Final dates are those 22 Finaled rows without `IssueDate`. Optional In Review / Inactive dates left as-is.

### FINAL_DATE — Final rows completed; 28 spurious on non-Final

- Ideal: populated for Final.
- All 972 pre-repair Final (`CaseStatus=Finaled`) rows already have `FINAL_DATE` equal to `entity.FinalDate`.
- 23 Finaled→Final remaps had `FinalDate` but null `FINAL_DATE` → **FILLED 23**.
- 28 non-Final rows carried `FINAL_DATE` from `entity.FinalDate` (Issued×20, Exempt×3, Expired×2, Canceled×1, Denied×1, In Review×1). Cleared as FIXED — same convention as Hawthorne / Glendale.

After repair: Final 995/995 (100%); Active / In Review / Inactive have none.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 0 | 33 | 0 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 2 | 0 | 476 → 474 |
| `FINAL_DATE` | 23 | 28 | 999 → 1,004 |

Missing `FINAL_DATE` rises because 28 non-Final spurious values are cleared while 23 Final fills are added (net +5 missing overall); among Final rows coverage is 995 / 995 (100%).

| STATUS_NORMALIZED | Before | After |
| --- | --- | --- |
| Final | 972 | 995 |
| Active | 519 | 490 |
| In Review | 283 | 281 |
| Inactive | 225 | 233 |

| Status (after) | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 490 / 490 (100%) | 0 / 490 |
| Final | 973 / 995 (97.8%) | 995 / 995 (100%) |
| In Review | 18 / 281 (6.4%) | 0 / 281 |
| Inactive | 44 / 233 (18.9%) | 0 / 233 |

## Artifacts

- Script: `agent/scripts/data_repair_ca_los_angeles_county.py` (`data_repair`)
- Report: `agent/reports/2026-07-24-los-angeles-county-data-repair.md`
