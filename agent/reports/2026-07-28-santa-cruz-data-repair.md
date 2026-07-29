# Santa Cruz (CA) data repair

**Summary:** Assessed Santa Cruz's 2,001-row sample and wrote `agent/scripts/ca/data_repair_ca_santa_cruz.py`. Santa Cruz uses a civic portal payload (`permit_info` + `search_data` + `inspections`). The repair fixes 75 stale statuses (mostly FINALED left Active, PAYMENT/UPLOAD AUTHORIZED wrongly Final, EXPIRED left Active), fills 92 PERMIT_DATEs from Issued/Approved, fills 31 FINAL_DATEs (26 from PermitFinaledDate, 5 from passed job-final inspections), and clears 4 spurious FINAL_DATEs on Inactive shells. After repair, FILE_DATE is 100% populated, Active/Final PERMIT_DATE coverage is 99.7%, and Final FINAL_DATE coverage is 99.4%.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Santa Cruz, CA**.

## DATA schema

All 2,001 rows have DATA. Single top-level key set:
`contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`.

Content variants (`INFERRED_SCHEMA`) by which permit_info dates are populated:

| Schema | N |
| --- | --- |
| `permit_info_issued_finaled` | 1,360 |
| `permit_info_issued` | 378 |
| `permit_info_applied_only` | 155 |
| `permit_info_finaled_only` | 56 |
| `permit_info_approved_only` | 52 |

Canonical mappings from DATA:

- `permit_info.PermitStatus` (= `search_data.Status`) → `STATUS_NORMALIZED`
- `permit_info.PermitAppliedDate` → `FILE_DATE`
- `permit_info.PermitIssuedDate` (fallback `PermitApprovedDate`) → `PERMIT_DATE`
- `permit_info.PermitFinaledDate` (fallback: passed job-final inspection) → `FINAL_DATE`

`search_data` date mirrors (`Applied Date` / `Issued Date` / `Finaled Date`) match `permit_info` exactly in this sample. `PermitExpirationDate` is a validity window, not a completion date.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,424 / Active 377 / In Review 101 / Inactive 99 / missing 0.

Root cause: `STATUS_NORMALIZED` was derived from stale `STATUS_ORIGINAL` labels that lag the live `PermitStatus` in DATA (e.g. original=`issued` while portal status is now `FINALED` or `EXPIRED`). Separately, `payment authorized` / `upload authorized` were globally mapped to Final despite being pre-issuance workflow states.

Issues repaired (75 FIXED):

| PermitStatus | Before → After | N |
| --- | --- | --- |
| FINALED | Active → Final | 21 |
| PAYMENT AUTHORIZED | Final → In Review | 20 |
| EXPIRED | Active → Inactive | 15 |
| ISSUED | In Review → Active | 5 |
| FINALED | Inactive → Final | 3 |
| ISSUED | Final → Active | 2 |
| UPLOAD AUTHORIZED | Final → In Review | 2 |
| WITHDRAWN | Active → Inactive | 1 |
| FINALED | In Review → Final | 1 |
| PAYMENT AUTHORIZED | Final → Active (has Issued) | 1 |
| APPROVED | Active → Final (has FinaledDate) | 1 |
| LAPSED / PAID / REVISIONS APPROVED | In Review → Active (has Issued) | 3 |

Intermediate final inspections (roof / plumbing / planning) are common on still-ISSUED shells and are **not** used to override PermitStatus.

After: Final 1,425 / Active 350 / In Review 114 / Inactive 112.

### FILE_DATE

Before: 0 missing. All 2,001 FILE_DATE values match `PermitAppliedDate` at calendar-day resolution.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 100%.

### PERMIT_DATE

Before: 274 missing. Where both present, PERMIT_DATE already matched PermitIssuedDate (1,727/1,727).

Repair: **92 FILLED, 0 FIXED** — mostly FINALED shells filled from Approved (53) and APPROVED Active shells filled from Approved (23), plus ISSUED rows filled from Issued/Approved (14).

Remaining Active/Final gap: **5** (FINALED 4, APPROVED 1) — no Issued or Approved date in DATA. Active coverage after repair: **349 / 350 (99.7%)**; Final: **1,421 / 1,425 (99.7%)**.

### FINAL_DATE

Before: 611 missing. Nearly all Final rows already matched PermitFinaledDate. **4 Inactive** rows (Withdrawn / Void) carried FINAL_DATE from closure stamps.

Repair: **31 FILLED** (26 from PermitFinaledDate on status-promoted / previously missing Final rows; 5 from passed job-final inspections on FINALED shells lacking PermitFinaledDate), **4 FIXED** (cleared spurious Inactive closure stamps).

Final coverage after repair: **1,417 / 1,425 (99.4%)**. Remaining 8 FINALED shells lack PermitFinaledDate and have no usable job-final inspection. No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_santa_cruz.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky (Expired / Withdrawn / Void / Canceled); canonical PermitFinaledDate on non-inactive rows → Final; In Review + Issued → Active; else PermitStatus map (PAYMENT/UPLOAD AUTHORIZED / PAID / UNDER REVIEW → In Review; ISSUED / NOT FINALED / APPROVED → Active; FINALED → Final).

### Performance (n=2,001)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 75 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 92 | 0 | 274 | 182 |
| FINAL_DATE | 31 | 4 | 611 | 584 |

### Ideal coverage after repair

| Rule | Coverage |
| --- | --- |
| FILE_DATE present (all) | 2,001 / 2,001 (100%) |
| PERMIT_DATE on Active | 349 / 350 (99.7%) |
| PERMIT_DATE on Final | 1,421 / 1,425 (99.7%) |
| FINAL_DATE on Final | 1,417 / 1,425 (99.4%) |
| FINAL_DATE absent on non-Final | 576 / 576 (100%) |

### Artifact

`AGENT_DATA_PATH/repaired/permits_ca_santa_cruz_repaired.parquet`
