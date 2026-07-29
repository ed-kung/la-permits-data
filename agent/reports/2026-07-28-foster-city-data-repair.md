# Foster City (CA) data repair

Repaired STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for Foster City using the civic-portal `permit_info` fields in DATA. Status was already correct on almost all rows; the main gains were filling five missing PERMIT_DATE values and seventeen missing FINAL_DATE values (two from PermitFinaledDate after status fixes, fifteen from passed final inspections). FILE_DATE needed no changes. Many legacy CLOSED shells still lack issuance and finaling timestamps in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py` script: **Foster City, CA**.

## Data shape

2,000 sample rows. Every row has the same top-level DATA keys: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Canonical fields are under `permit_info`:

| DATA field | Target column |
| --- | --- |
| `PermitStatus` | `STATUS_NORMALIZED` |
| `PermitAppliedDate` | `FILE_DATE` |
| `PermitIssuedDate` (else `PermitApprovedDate`) | `PERMIT_DATE` |
| `PermitFinaledDate` (else passed final inspection) | `FINAL_DATE` |

### INFERRED_SCHEMA (after repair)

| Schema | n |
| --- | ---: |
| permit_info_issued_finaled | 1,468 |
| permit_info_applied_only | 238 |
| permit_info_finaled_only | 150 |
| permit_info_issued | 138 |
| permit_info_approved_only | 6 |

(One CLOSED row with Issued/Approved `4/27/2049` is classified as `permit_info_finaled_only` because implausible years are rejected.)

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,806 / Active 88 / Inactive 72 / In Review 31 / missing 3.

Almost all rows already matched `PermitStatus` (CLOSED/FINALED→Final, ISSUED/APPROVED/ACTIVE→Active, EXPIRED/WITHDRAWN/CANCELED/PERMIT REVOKED→Inactive, review/waiting/hold labels→In Review).

Five errors came from `STATUS_ORIGINAL` lagging `PermitStatus`:

| Permit # | PermitStatus | Before | After | Flag |
| --- | --- | --- | --- | --- |
| BLDG2024-0337 | ISSUED | (null) | Active | FILLED |
| MECH2023-0094 | EXPIRED | (null) | Inactive | FILLED |
| BLDG2024-0379 | UNDER REVIEW | (null) | In Review | FILLED |
| BLDG2024-0292 | FINALED | Active | Final | FIXED |
| BLDG2024-0346 | FINALED | In Review | Final | FIXED |

Root cause: upstream normalization used a stale `STATUS_ORIGINAL` (e.g. “waiting for applicant response”, “issued”, “pending payment”) instead of the current `PermitStatus`. Non-inactive rows with `PermitFinaledDate` are treated as Final.

After repair: Final 1,808 / Active 88 / Inactive 73 / In Review 31 / missing 0.

### FILE_DATE

Already populated on all 2,000 rows and identical to `PermitAppliedDate`. No FILLED/FIXED.

### PERMIT_DATE

Before: 396 missing. Upstream used `PermitIssuedDate` when present (1,604 matches); never fell back to `PermitApprovedDate`.

Repairs: **5 FILLED** (1 ISSUED + 1 FINALED after status fix + 3 ACTIVE/APPROVED shells with Approved only).

Left missing: 391, including ~330 Final CLOSED/FINALED legacy shells with blank Issued/Approved, plus one CLOSED row whose Issued/Approved dates are year **2049** (rejected as implausible). Active coverage after repair: **88/88 (100%)**. Final: **1,478/1,808 (81.7%)**.

Two pre-existing chronology quirks remain (`PERMIT_DATE` one–three days before `FILE_DATE`); both match DATA and were not changed.

### FINAL_DATE

Before: 384 missing. Upstream matched `PermitFinaledDate` when present (1,616 matches). No non-Final rows carried a spurious FINAL_DATE.

Repairs: **17 FILLED** — 2 from `PermitFinaledDate` on the status-fixed FINALED rows, 15 from latest passed final inspection (`Type` matching final / C of O patterns with APPROVED/PASS-style `Result`).

Left missing: 367 overall; **175 Final** rows still lack both `PermitFinaledDate` and a usable passed final inspection (often empty `inspections` on older CLOSED conversions).

After repair, Final FINAL_DATE coverage: **1,633/1,808 (90.3%)**. Non-Final statuses have 0 FINAL_DATE.

## Repair performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 2 | 3 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 5 | 0 | 396 → 391 |
| FINAL_DATE | 17 | 0 | 384 → 367 |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_foster_city.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_foster_city_repaired.parquet`
