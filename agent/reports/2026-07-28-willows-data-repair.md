# Willows (CA) data repair

**Summary:** Assessed Willows's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_willows.py`. Willows uses a civic portal payload (`permit_info` + `search_data`). The repair fills 5 missing statuses and fixes 42 incorrect ones (mostly "No Permit Needed" / "VOID- CLOSE OUT" mislabeled as Final, and "Pending-Final Inspection" mislabeled as Active), and fills 135 missing PERMIT_DATEs from Issued/Approved. FILE_DATE and FINAL_DATE already match `permit_info` whenever those portal dates exist; remaining gaps have no source date in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Willows, CA**.

## DATA schema

All 2,000 rows have DATA. Top-level keys are always `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Inferred content variants:

| Schema | N | Notes |
| --- | --- | --- |
| `permit_info_issued` | 885 | Issued present, Finaled blank |
| `permit_info_issued_finaled` | 658 | Issued + Finaled present |
| `permit_info_applied_only` | 261 | Only Applied populated |
| `permit_info_approved_only` | 144 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 21 | Finaled present, Issued blank |
| `permit_info_empty` | 16 | Blank status and no usable dates |
| `permit_info_empty_dates` | 10 | Status present, no usable dates |
| `legacy_no_status` | 5 | Blank PermitStatus with dates |

Canonical mappings from DATA:

- `permit_info.PermitStatus` → `STATUS_NORMALIZED` (with Finaled / Issued overrides)
- `permit_info.PermitAppliedDate` (fallback `search_data.Application`) → `FILE_DATE`
- `permit_info.PermitIssuedDate` (fallback `PermitApprovedDate` / `search_data.Issued`) → `PERMIT_DATE`
- `permit_info.PermitFinaledDate` (fallback `search_data.FINALED` / final inspection) → `FINAL_DATE`

`PermitExpirationDate` is a validity window, not a completion date. Portal status strings are often truncated to 15 characters (`No Permit Neede`, `Completed (Sign`, `Pending-Final I`).

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,101 / Active 629 / In Review 219 / Inactive 30 / missing 21.

Issues:

1. **Missing (21):** Blank `PermitStatus` on HIST-ENCROACHMENT / ENCROACHMENT shells. 5 have usable dates → FILLED (3 In Review from Applied, 1 Active from Approved, 1 Final from Finaled). 16 have no dates → left missing.
2. **Incorrect (37 sticky mislabels + 5 date-driven promotions):**
   - 29 `No Permit Neede` and 1 `VOID- CLOSE OUT` mapped to Final → Inactive.
   - 7 `Pending-Final I` (no Issued/Approved) mapped to Active → In Review.
   - 3 `UNDER REVIEW` shells that already carry `PermitIssuedDate` → Active.
   - 2 `ACTIVE` shells with `PermitFinaledDate` → Final.

Repair performance: **5 FILLED, 42 FIXED**; missing after: **16**.

After: Final 1,074 / Active 624 / In Review 226 / Inactive 60 / missing 16.

### FILE_DATE

Before: 432 missing. Where both present, FILE_DATE matches `PermitAppliedDate` exactly (1,568/1,568).

Of the 432 Applied-blank rows, 405 carry Approved=Issued (converted well / sewage / monitoring-well records) and 26 have no dates at all. Following civic-portal convention, Approved/Issued are not used as application-date substitutes.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 78.4% (1,568 / 2,000).

### PERMIT_DATE

Before: 457 missing. Where Issued is present, PERMIT_DATE matches exactly (1,543/1,543). 157 Active/Final rows had Approved but no Issued and a null PERMIT_DATE.

Repair: **135 FILLED, 0 FIXED** — Issued/Approved backfill on Active/Final rows (PERMIT ISSUED, APPROVED, ISSUED, FINALED, Completed shells). Rows reclassified to Inactive (`No Permit Neede`) are not filled.

Remaining Active/Final gap: **30** (FINALED 17, Completed (Sign 8, APPROVED 4, ACTIVE 1) — all lack both Issued and Approved in DATA.

After repair: Active PERMIT coverage **619 / 624 (99.2%)**; Final **1,049 / 1,074 (97.7%)**.

### FINAL_DATE

Before: 1,320 missing. Where both present, FINAL_DATE matches `PermitFinaledDate` exactly (680/680). No non-Final rows carried a spurious FINAL_DATE after status repair (2 Active shells with Finaled were promoted to Final).

323 `FINALED` and 71 `Completed (Sign` Final rows have blank `PermitFinaledDate`, empty `search_data.FINALED`, and no usable final inspections → unrepairable.

Repair: **0 FILLED, 0 FIXED**. Final coverage after repair: **680 / 1,074 (63.3%)**.

Two source chronology inversions remain (`PermitIssuedDate` after `PermitFinaledDate` in DATA); both dates are copied as-is.

## Repair script

`agent/scripts/ca/data_repair_ca_willows.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky (`No Permit Needed`, VOID*, EXPIRED, CANCELLED); Finaled date → Final; In Review + Issued → Active; else PermitStatus map (including truncated labels); blank status inferred from Applied / Approved / Issued / Finaled.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 5 | 42 | 21 | 16 |
| FILE_DATE | 0 | 0 | 432 | 432 |
| PERMIT_DATE | 135 | 0 | 457 | 322 |
| FINAL_DATE | 0 | 0 | 1,320 | 1,320 |

### Artifact

`AGENT_DATA_PATH/repaired/permits_ca_willows_repaired.parquet`
