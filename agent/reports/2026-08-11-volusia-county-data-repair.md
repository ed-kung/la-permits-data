# Volusia County (FL) data repair

Summary: Volusia County was the first FL sample jurisdiction without a repair script after Jacksonville through Pinellas County. Of 1,999 sample rows, 1,557 are `folder_list` search payloads (all status/dates null upstream) and 442 are `folder_detail` records. The dominant detail-schema defect is that every non-null `FINAL_DATE` (395 rows) equals `Folder details.Expiration` — a permit validity window, not completion — matching the Sarasota EnerGov Expiration bug. Repair fills all 1,560 missing statuses and 1,557 missing `FILE_DATE` values from DATA, and clears all 395 incorrect `FINAL_DATE` values. No true finalization timestamp exists in DATA, so Final rows remain without `FINAL_DATE`. `PERMIT_DATE` already matched `Issuance` when present; list rows expose no issuance field.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Volusia County, FL**
- Sample size: **1,999** records

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `folder_list` | 1,557 | Top-level `Status`, `Date` / `request_date`, `File Number`, `Type`; no Issuance or finalization fields |
| `folder_detail` | 442 | `Folder details` (Status, Application, Issuance, Expiration) + `Folder information` / Parcel / People |

Canonical field sources:

- `Status` / `Folder details.Status` → `STATUS_NORMALIZED`
- `Date` / `request_date` / `Application` → `FILE_DATE`
- `Folder details.Issuance` → `PERMIT_DATE`
- No reliable finalization date in DATA → `FINAL_DATE` (Expiration is not used; `Last Activity Date` is general activity and not used)

## Findings by field

### STATUS_NORMALIZED

- Before: missing **1,560**; Final 320; Inactive 56; Active 48; In Review 15.
- **folder_list (1,557):** `STATUS_ORIGINAL` and `STATUS_NORMALIZED` are entirely null. `DATA.Status` is always present (`Finaled` 545, `Closed` 463, `Cancelled` 98, `Complete` 93, `Cert of Occupancy` 83, `Approved` 73, …).
- **folder_detail (442):** Upstream mapping from `STATUS_ORIGINAL` is nearly complete. Gaps: **2** `Dept Review` and **1** `Final Fees Due` left null.
- Repair:
  - **1,557 FILLED** from `folder_list` Status
  - **3 FILLED** on `folder_detail` (`Dept Review` → In Review; `Final Fees Due` → Active)
  - **0 FIXED** (no incorrect non-null statuses observed)
- After: missing **0**; Final 1,504; Inactive 300; Active 154; In Review 41.

### FILE_DATE

- Before: **1,557** missing — all on `folder_list`. All 442 `folder_detail` rows already match `Application` at day resolution.
- On `folder_list`, `Date` equals `request_date` for every row and is a usable application/submittal date.
- Repair: **1,557 FILLED**, **0 FIXED**. Missing after: **0**.
- Coverage after repair: **100%** for Active / Final / In Review / Inactive.

### PERMIT_DATE

- Before: 1,640 missing.
- **folder_detail:** Every non-empty `Issuance` already matched `PERMIT_DATE` (359/359). All 320 Final detail rows have `PERMIT_DATE`. Active gaps are `Approved` rows with empty `Issuance` (37/48 before status repair; 37/49 after adding Final Fees Due, which already had Issuance/PERMIT).
- **folder_list:** No issuance field → cannot fill after status repair (1,184 newly Final / 105 Active list rows stay without `PERMIT_DATE`).
- Repair: **0 FILLED**, **0 FIXED**.
- After repair coverage: Active **12/154 (7.8%)**; Final **320/1,504 (21.3%)**. Among `folder_detail` only: Active **12/49 (24.5%)**; Final **320/320 (100%)**.

### FINAL_DATE

- Before: 1,604 missing. Among the 395 non-null values (all on `folder_detail`), **395/395** equal `Folder details.Expiration`.
- Breakdown of Expiration copies by upstream status: Final 302, Inactive 53, Active 38, In Review 1, null status 1.
- `Last Activity Date` (present on 133 detail rows) falls between Issuance and Expiration when both exist, but is a general activity stamp — not used as finalization.
- Repair: **0 FILLED**, **395 FIXED** (cleared Expiration mislabels, including all non-Final spurious finals).
- After: missing **1,999** (0% of Final rows have `FINAL_DATE`). No remaining `FINAL_DATE` equals Expiration.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_volusia_county.py` (`data_repair`)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1,560 | 0 | 1,560 | 0 |
| FILE_DATE | 1,557 | 0 | 1,557 | 0 |
| PERMIT_DATE | 0 | 0 | 1,640 | 1,640 |
| FINAL_DATE | 0 | 395 | 1,604 | 1,999 |

Coverage after repair (share non-null):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 154 | 100% | 7.8% | 0% |
| Final | 1,504 | 100% | 21.3% | 0% |
| In Review | 41 | 100% | 0% | 0% |
| Inactive | 300 | 100% | 9.0% | 0% |

`FINAL_DATE` missing rises because incorrect Expiration copies were cleared and DATA has no replacement finalization date. `PERMIT_DATE` coverage looks low overall only because `folder_list` rows (78% of the sample) never expose an issuance timestamp.

## Not repairable / left as-is

- `folder_list` Active / Final rows: no `Issuance` or finalization fields → `PERMIT_DATE` / `FINAL_DATE` stay missing.
- `folder_detail` Active (`Approved`) with empty `Issuance` → `PERMIT_DATE` stays missing.
- All Final rows after Expiration clears: no Certificate / Final inspection / finaled date in DATA → `FINAL_DATE` stays missing.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_volusia_county.py`
- Repaired sample parquet: `AGENT_DATA_PATH/volusia_county_repaired_sample.parquet`
