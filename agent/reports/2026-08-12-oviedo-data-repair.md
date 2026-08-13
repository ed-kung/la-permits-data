# Oviedo (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Oviedo**. DATA is the Lake Mary / Punta Gorda city-portal family (`permit_status_detail` + inspections, sparse `fees_detail`, and `mini_set` application shells). Upstream status mapping was correct for all 1,694 full-permit rows but left 306 nulls on shells lacking `Status for Permit Number`. `FILE_DATE` already matched `Application Date` wherever that field exists (1,759/2,000). `PERMIT_DATE` was null on every row despite `Permit Issue Date` on 1,678 full-permit records. `FINAL_DATE` was present on 1,415/1,635 Final rows, mostly from inspections; 11 pre-issue Notice-of-Commencement stamps were cleared and 3 drifted values corrected. After repair: STATUS 100%; FILE_DATE 87.9%; Active/Final PERMIT_DATE 100%/86.2% (99.3% among originally Final); Final FINAL_DATE 74.6% (85.9% among originally Final).

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Oviedo, FL** → `agent/scripts/fl/data_repair_fl_oviedo.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `permit_status` | 1,694 | `detail` / `fees` + `permit_status_detail` + `insp_status_detail` |
| `application` | 241 | `mini_set` with `application_status` / `application_type` only |
| `fees_detail` | 65 | `detail` + `fees` + `fees_total` (Application Date/Status; no issue/inspections) |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number` (full); else `Application Status` / `application_status` |
| FILE_DATE | `Application Date` (`permit_status_detail` or `detail`) |
| PERMIT_DATE | `Permit Issue Date` |
| FINAL_DATE | Latest successful (`APPROVED` / `WAIVED` / partial-approve) inspection excluding Notice of Commencement |

`CO Issue Date` is present on full rows but is often a multi-year admin batch stamp (median ~1,100+ days after issue when `FINAL_DATE` is missing) and is **not** used as a completion date.

## Field assessments

### STATUS_NORMALIZED

| Status for Permit Number / app status | n | Upstream | Assessment |
| --- | ---: | --- | --- |
| CLOSED | 1,515 | Final | Correct |
| C.O. ISSUED | 109 | Final | Correct |
| PERMIT PRINTED | 52 | Active | Correct |
| FINAL INSPECTION COMPLETE | 11 | Final | Correct |
| TO BE ISSUED | 5 | In Review | Correct |
| PERMIT REVOKED | 2 | Inactive | Correct |
| *(null STATUS — application / fees_detail)* | 306 | **null** | Fill from Application Status / `application_status` |

Null-status fills: Final 249 (`CLOSED` / `CLOSED BY REPORT` / `CERTIFICATE OF OCCUPANCY`), Inactive 38 (`EXPIRED` / `ABANDONED` / `REJECTED`), In Review 13 (`EPLAN REVIEW` / `IN PLAN CHECK` / `APPROVED`), Active 6 (`PERMIT ISSUED`).

**Root cause:** Upstream only mapped `Status for Permit Number`. Shell schemas expose Application Status only.

**Repair performance:** FILLED 306, FIXED 0; missing 306 → 0.

### FILE_DATE

- Before: missing on **241 / 2,000** (all `application` mini_set rows).
- All 1,694 `permit_status` and 65 `fees_detail` values already equal `Application Date` (0 mismatches).
- Mini_set rows have no application date → not fillable.

**Repair performance:** FILLED 0, FIXED 0; coverage 87.9%. Date order: `FILE_DATE > PERMIT_DATE` = 0.

### PERMIT_DATE

- Before: NaN on **2,000 / 2,000** (never populated upstream).
- `Permit Issue Date` available on 1,678 / 1,694 full-permit rows → FILLED.
- Remaining gaps: 241 application + 65 fees_detail (no issue field) + 11 Final / 5 In Review full rows with blank `Permit Issue Date`.
- Active coverage after repair: **100%** (52/52 originally Active). Originally Final: **99.3%** (1,624/1,635). Overall Final including newly filled shell Finals: 86.2%.

**Repair performance:** FILLED 1,678, FIXED 0. All filled values match `Permit Issue Date`.

### FINAL_DATE

- Before: present on 1,415 / 1,635 Final; missing on all non-Final (correct).
- Source: latest non-NOC successful inspection. Preferring FINAL-named rows alone was rejected — Oviedo often stamps a later BACKFLOW / misc approval after an earlier `* FINAL` row.
- Pre-issue FINAL values that only reflected Notice of Commencement → cleared (10).
- 3 drifted values FIXED to the latest successful non-NOC inspection.
- ~220 originally Final CLOSED shells have no usable non-NOC successful inspection → remain missing; `CO Issue Date` not used.
- Newly filled Final shells (249) also lack inspections → FINAL stays missing.
- 4 remaining `PERMIT_DATE > FINAL_DATE` cases are agency quirks (successful inspection 1–90 days before recorded issue date).

**Repair performance:** FILLED 0, FIXED 13 (10 clears + 3 replacements). Final coverage 74.6% overall; 85.9% among originally Final.

## Artifacts

| Path | Description |
| --- | --- |
| `agent/scripts/fl/data_repair_fl_oviedo.py` | `data_repair()` implementation |
| `AGENT_DATA_PATH/oviedo_permits_repaired.parquet` | Repaired sample output |
