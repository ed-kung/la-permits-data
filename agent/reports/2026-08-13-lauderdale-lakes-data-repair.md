# Lauderdale Lakes (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Lauderdale Lakes**. DATA is a uniform city-portal payload (`app`, `fees`, `permit`, `init_info`, `permit_list`, `inspection_list`) with 6-column inspection rows `[type, party, date, result, fee, due]`. Upstream left `STATUS_NORMALIZED` null on 1,975/2,000 rows (only `WITHDRAWN / VOID` → Inactive); repair filled all statuses from `app.Status` plus issuance signals. `FILE_DATE` and `PERMIT_DATE` already matched `Application Received Date` / `Issued Date` wherever those fields exist (0 fills/fixes). `FINAL_DATE` was missing on every row; filled for 1,623/1,657 Final rows from PASS inspections (prefer `FINAL*`). After repair: STATUS 0 null; FILE_DATE 100%; Active/Final PERMIT_DATE 927/1,705 (54.4%); Final FINAL_DATE 1,623/1,657 (97.9%); 0 date inversions.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs. Lauderdale Lakes was the first pair without `agent/scripts/fl/data_repair_fl_lauderdale_lakes.py`.

## DATA shape

All 2,000 rows share the same top-level key set. Content variants (INFERRED_SCHEMA):

| Schema | n | Role |
| --- | ---: | --- |
| `city_app_permit_no_issued` | 967 | Non-empty `permit`, blank Issued Date |
| `city_app_issued_insp` | 926 | Issued Date + dated inspections |
| `city_app_issued` | 60 | Issued Date, no dated inspections |
| `city_app_app_only` | 47 | Empty `permit` object |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `app.Status`, refined by `permit.Permit Status`, Issued Date, and `permit_list` ISSUED/COMPLETED |
| FILE_DATE | `app.Application Received Date` |
| PERMIT_DATE | `permit.Issued Date` |
| FINAL_DATE | Latest PASS / PASS PARTIAL / IN COMPLIANCE inspection (prefer types matching FINAL*/certificate/occupancy); floored at Issued Date |

## Field assessments

### STATUS_NORMALIZED

Before: **1,975 null**, 25 Inactive. `STATUS_ORIGINAL` matches live `app.Status` (case-normalized) on every row; upstream normalization simply failed for nearly all labels.

| app.Status | n | After repair |
| --- | ---: | --- |
| COMPLETE / CLOSED | 1,656 | Final |
| EXPIRED / CLOSED | 89 | Inactive |
| WITHDRAWN / CLOSED | 76 | Inactive |
| ACTIVE / PENDING | 60 | In Review (57) / Active (3 with Issued Date) |
| WITHDRAWN / VOID | 25 | Inactive (already correct) |
| ACTIVE / READY TO ISSUE | 22 | In Review (13) / Active (9 with Issued Date) |
| ACTIVE / READY TO CLOSE | 20 | Active |
| ACTIVE / ISSUED | 16 | Active |
| ACTIVE / WITHDRAWN | 9 | Inactive |
| ACTIVE / CLOSED | 6 | Inactive |
| COMPLETE / VOID | 6 | Inactive |
| ENTERED IN ERROR / CLOSED | 5 | Inactive |
| ACTIVE / EXPIRED | 4 | Inactive |
| Other terminal / edge labels | 6 | Inactive or Final |

Flags: **1,975 FILLED, 0 FIXED**. After: Final 1,657; Inactive 225; In Review 70; Active 48; **0 null**.

### FILE_DATE

Missing on 0/2,000 before. Calendar day matches `Application Received Date` on all 2,000 rows. Flags: **0 FILLED, 0 FIXED**. Coverage after: **100%** for every status.

### PERMIT_DATE

Missing on 1,014/2,000 before. Every non-null `PERMIT_DATE` already matched `permit.Issued Date`; no Issued Date existed without a matching PERMIT_DATE. Many Complete/Active shells only show FEE or ISSUED on `permit_list` (no issuance timestamp) — not repairable.

| Status (after) | PERMIT_DATE coverage |
| --- | --- |
| Active | 31 / 48 (64.6%) |
| Final | 896 / 1,657 (54.1%) |
| In Review | 0 / 70 (correctly blank) |
| Inactive | 59 / 225 (26.2%) |

Active/Final coverage: **927/1,705 (54.4%)**. Flags: **0 FILLED, 0 FIXED**.

### FINAL_DATE

Missing on 2,000/2,000 before. Inspection rows include many `FINAL BUILDING` / `FINAL ROOF` / `FINAL ELECTRICAL` / etc. with PASS results that were never ingested.

| Repair action | n |
| --- | ---: |
| FILLED for Final from PASS inspections | 1,623 |
| Final still missing (no dated PASS; FAIL-only or empty list) | 34 |
| Cleared on non-Final (none had values) | 0 |

Of the 1,623 fills, 1,251 use `FINAL*` / certificate-style PASS types; 372 fall back to any PASS-like result. After: Final FINAL_DATE **1,623/1,657 (97.9%)**. Flags: **1,623 FILLED, 0 FIXED**. Date order checks: 0 `FILE_DATE > PERMIT_DATE`, 0 `PERMIT_DATE > FINAL_DATE`.

## Repair script

- Script: `agent/scripts/fl/data_repair_fl_lauderdale_lakes.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/lauderdale_lakes_repaired_sample.parquet`
