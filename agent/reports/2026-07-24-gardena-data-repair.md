# Gardena CA data repair

**Summary:** Gardena’s 2,000 sample records share one DATA schema (`permit_info_search_data`). Upstream dates already match `permit_info` when present. The main gaps are status (199 null empty-`PermitStatus` rows; 33 rows with `PermitFinaledDate` but non-Final labels) and missing dates on otherwise complete records. Repair fills all null statuses, reclassifies finaled rows to Final, adds 17 `PERMIT_DATE` values from `PermitApprovedDate`/`Issued`, and 26 `FINAL_DATE` values (1 from `PermitFinaledDate`, 25 from finaling inspections). `FILE_DATE` needs no changes (5 empty-Applied rows remain unfillable). Script: `agent/scripts/data_repair_ca_gardena.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Gardena"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Gardena, CA (after Alhambra … El Segundo) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `permit_info_search_data` | 2,000 |

All rows share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (asterisks stripped; override to Final if `PermitFinaledDate` present; empty status inferred from dates) |
| `FILE_DATE` | `permit_info.PermitAppliedDate` |
| `PERMIT_DATE` | `permit_info.PermitIssuedDate`; fallback `PermitApprovedDate` / `search_data.APPROVED` |
| `FINAL_DATE` | `permit_info.PermitFinaledDate` (= `search_data.FINALED`); fallback for Final rows: finaling inspection `Completed` |

`PermitExpirationDate` / `search_data.EXPIRED` are validity windows, not completion dates.

## Field assessment

### STATUS_NORMALIZED — 199 missing + 33 stale labels

`STATUS_ORIGINAL` usually matches lowercased `PermitStatus`, but portal labels often carry asterisk decorations (`**FINALED**`, `FINALED**`, `**EXPIRED**`). Upstream mapping covered labeled rows; gaps:

| Issue | n | Notes |
| --- | --- | --- |
| Empty `PermitStatus` → null status | 197 | Dates often present (102 finaled, 80 issued-only, 15 applied-only) |
| `PL CK ONLY` / `<NONE>` → null | 2 | |
| `PermitFinaledDate` present but status not Final | 33 | WAIVED×23, ISSUED×7, EXPIRED×1, EXPIRED PL CK×1, plus one `**FINALED**` mislabeled Active (`STATUS_ORIGINAL` = issued) |

Repairs:

| Before | After | Reason | n | Flag |
| --- | --- | --- | --- | --- |
| null | Final | empty/`<NONE>` + `PermitFinaledDate` | 102 | FILLED |
| null | Active | empty + Issued/Approved | 81 | FILLED |
| null | In Review | empty applied-only / `PL CK ONLY` | 16 | FILLED |
| In Review | Final | WAIVED + `PermitFinaledDate` | 23 | FIXED |
| Active | Final | ISSUED/`FINALED` + `PermitFinaledDate` | 8 | FIXED |
| Inactive | Final | EXPIRED / EXPIRED PL CK + `PermitFinaledDate` | 2 | FIXED |

After repair: Final 1,376, Inactive 311, Active 225, In Review 88 (**0 missing**).

### FILE_DATE — correct where DATA has an application date (0 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- 1,995 / 2,000 match `PermitAppliedDate` exactly (0 mismatches).
- **Not repairable:** 5 rows have empty Applied (APPLIED, WITHDRAWN×2, ISSUED, and one empty-status row that does have Issued). No alternate application field in `search_data` / fees / contacts.

### PERMIT_DATE — correct when Issued present; 17 fillable

- Ideal: populated for Active and Final.
- When both present, `PERMIT_DATE` always equals `PermitIssuedDate` (0 mismatches).
- 320 rows missing upstream; Active/Final with Approved (or rare Issued) can be filled.

| Action | n |
| --- | --- |
| FILLED from Issued/Approved (Active/Final) | 17 |
| FIXED | 0 |

After repair coverage: Active 221/225 (98.2%), Final 1,221/1,376 (88.7%).

**Not repairable:** 4 Active and ~155 Final rows lack both Issued and Approved. `FILE_DATE` is not used as a proxy.

### FINAL_DATE — correct when Finaled present; 26 fillable

- Ideal: populated for Final.
- When both present, `FINAL_DATE` always equals `PermitFinaledDate` / `search_data.FINALED` (0 mismatches).
- 32 upstream Final rows lack `PermitFinaledDate`; many have finaling inspections (`Result` contains FINALED, or Type contains FINAL with PASSED/APPROVED/empty/etc.). Failed-only finals are not used.

| Action | n |
| --- | --- |
| FILLED from `PermitFinaledDate` (status corrected to Final) | 1 |
| FILLED from finaling inspection `Completed` | 25 |
| FIXED | 0 |

After repair coverage: Final 1,369/1,376 (99.5%). No `FINAL_DATE` remains on non-Final rows.

**Not repairable:** 7 Final rows have neither `PermitFinaledDate` nor a usable finaling inspection (empty inspections, FAILED-only final electrical, plan-check-only, or non-final inspection types). Expiration is not used as a proxy.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 199 | 33 | 199 → 0 |
| `FILE_DATE` | 0 | 0 | 5 → 5 |
| `PERMIT_DATE` | 17 | 0 | 320 → 303 |
| `FINAL_DATE` | 26 | 0 | 657 → 631 |

## Artifacts

- Script: `agent/scripts/data_repair_ca_gardena.py` (`data_repair`)
- Report: `agent/reports/2026-07-24-gardena-data-repair.md`
