# Longwood (FL) data repair — 2026-08-13

Longwood’s sample (2,000 rows) is a SmartGov portal payload. Canonical status and dates live in `Build Status` and `My Project` (`Submitted` / `Issued` / `Approved` / `Closed`). Upstream `STATUS_NORMALIZED` often lagged behind the portal (Closed still labeled Active/Inactive/In Review; many nulls on Expired* and blank Build Status). The repair script fills/fixes status and dates from DATA; after repair, FILE_DATE is complete for all non-empty rows, Active/Final PERMIT_DATE is 99.9% complete, and Final FINAL_DATE is 99.8% complete.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_fl_sample.parquet` without
`agent/scripts/{state}/data_repair_{state}_{city}.py`: **Longwood, FL**.

## DATA shape

SmartGov community portal (same family as Lighthouse Point / Highland Beach):

| INFERRED_SCHEMA   | n    | Notes                                      |
| ----------------- | ---- | ------------------------------------------ |
| smartgov_full     | 1699 | + `ProjectDescription` (+ Parcel Number)   |
| smartgov_no_desc  | 276  | + Parcel Number, no description            |
| smartgov_minimal  | 16   | core keys only                             |
| smartgov_empty    | 9    | blank scraped shells                       |

Canonical sources:

- `DATA["Build Status"]` → STATUS_NORMALIZED (with Closed/Issued date overrides; Expired* sticky Inactive)
- `My Project.Submitted` (else `Created`) → FILE_DATE
- `My Project.Issued` (else `Approved`) → PERMIT_DATE
- `My Project.Closed` (else latest passed Final/COO inspection) → FINAL_DATE

## Findings before repair

### STATUS_NORMALIZED

| Value     | n    |
| --------- | ---- |
| Final     | 1043 |
| Inactive  | 468  |
| null      | 352  |
| Active    | 110  |
| In Review | 27   |

Main failure modes:

1. **Lagged STATUS_ORIGINAL vs current Build Status** — 61 Closed rows still Active (39), Inactive (13), or In Review (5) because STATUS_ORIGINAL was still `issued` / `expired` / `ready to issue`.
2. **Unmapped / null statuses** — 54 Expired* rows and 9 Return To Applicant rows had null STATUS_NORMALIZED; 282 null-Build-Status rows (applications with Permit Type + My Project dates but no Permit Number) were entirely null.
3. **Issued labeled In Review** — STATUS_ORIGINAL still `pending` / `ready to issue` while Build Status / Issued date already show issuance.
4. **Expired labeled Active** — 2 rows with STATUS_ORIGINAL=`issued` despite `Expired: …` Build Status.

### FILE_DATE

Nearly complete: 1,988/2,000 matched `My Project.Submitted`. 3 Closed rows missing FILE_DATE had a Submitted stamp; 7 remaining missing are empty shells (2 already carry FILE_DATE from upstream with empty DATA).

### PERMIT_DATE

1,814 matched Issued. Gaps concentrated on Closed/null-status rows with blank Issued but usable Approved, plus Issued stamps absent on some Final shells. One Final row had FINAL_DATE equal to Approved while Closed (and Issued) were later — PERMIT was also missing.

### FINAL_DATE

1,113 matched Closed. 61 rows had a Closed date but missing FINAL_DATE (mostly Closed mislabeled as Active/Inactive/In Review, or null status). One Final row used Approved (6/24/2024) instead of Closed (8/7/2024).

## Repair script

`agent/scripts/fl/data_repair_fl_longwood.py` — `data_repair(df)`.

Logic mirrors other SmartGov FL repairs: map Build Status with date overrides; fill/fix FILE/PERMIT/FINAL from My Project; clear FINAL_DATE when effective status is not Final; emit `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

## Performance on sample (n=2,000)

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | ------ | ----- | -------------- | ------------- |
| STATUS_NORMALIZED | 345    | 67    | 352            | 7             |
| FILE_DATE         | 3      | 0     | 10             | 7             |
| PERMIT_DATE       | 50     | 1     | 184            | 134           |
| FINAL_DATE        | 61     | 1     | 886            | 825           |

Status distribution after repair: Final 1,177 · Inactive 511 · Active 201 · In Review 104 · null 7.

Coverage after repair:

- FILE_DATE: 100% for Active / Final / In Review / Inactive
- PERMIT_DATE: Active 100%; Final 99.9% (1,176/1,177); In Review 0% (expected); Inactive 95.7%
- FINAL_DATE: Final 99.8% (1,175/1,177); 0% on non-Final

Largest status transitions: null→Active 124, null→In Review 90, null→Final 77, null→Inactive 54, Active→Final 39, Inactive→Final 13.

## Not repairable from DATA

- 7 `smartgov_empty` shells remain null-status (2 other empty shells already Inactive from STATUS_ORIGINAL only).
- 1 Final (`Closed`) with blank Issued and Approved → PERMIT_DATE stays missing.
- 2 `Finaled` rows with blank Closed and no inspections → FINAL_DATE stays missing.
- 2 Final rows have Issued after Closed in the portal (`PERMIT_DATE > FINAL_DATE`); stamps are preserved as published.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_longwood.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_fl_longwood_repaired.parquet`
