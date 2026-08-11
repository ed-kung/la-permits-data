# Sarasota County (FL) data repair

Summary: Sarasota County was the first FL sample jurisdiction without a repair script after Jacksonville and Lee County. DATA has two schemas — EnerGov `permit_info` (1,774) and Accela (227). The dominant defect is that every non-null `permit_info` `FINAL_DATE` was a copy of Expiration Date (1,127 rows); the repair replaces these with Certificate / Final inspection / last successful inspection Ended dates when available, or clears them. Status gaps and Accela lag cases are fully resolved. `FILE_DATE` was already correct for all 2,001 rows.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Sarasota County, FL** (Jacksonville and Lee County already have scripts)
- Sample size: **2,001** records

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `permit_info` | 1,774 | EnerGov payload: `Permit Details`, `Permit Info`, `Processes And Notes` |
| `accela` | 227 | Accela Citizen Access: `status`, `date`, `tasks`, `search_data`, etc. |

Canonical field sources:

**permit_info**

- `Permit Details.Status` → `STATUS_NORMALIZED`
- `Permit Details.Application Date` → `FILE_DATE`
- `Permit Details.Issue Date` → `PERMIT_DATE`
- `Processes And Notes` (CO/CC Issued, Final inspection, else last approved inspection) → `FINAL_DATE`

**accela**

- `DATA.status` → `STATUS_NORMALIZED`
- `DATA.date` / `search_data.Date` → `FILE_DATE`
- Permit Issuance / Issued → `PERMIT_DATE`
- Certificate Final CO Issued, else Inspection Final Inspection Complete → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,767; Active 98; Inactive 83; In Review 50; **missing 3**.
- Missing `permit_info` statuses (unmapped upstream): `Active/Current` → Active; `Lien Filed` → Inactive; `Progressive Enforcement` → Active.
- Accela corrections (3 FIXED):
  - `Pending CO` was Final → **Active** (certificate not yet issued)
  - Two rows with `DATA.status=Closed - Complete` but stale `STATUS_ORIGINAL` (`inspection phase` / `revisions required`) → **Final**
- After repair: Final 1,768; Active 100; Inactive 84; In Review 49; **0 missing**.

### FILE_DATE

- Already populated for all 2,001 rows.
- `permit_info`: 100% match `Application Date` (0 FIXED).
- `accela`: 100% match `DATA.date` / `search_data.Date` (0 FIXED).

### PERMIT_DATE

- Before: 531 missing. When present under `permit_info`, values always matched `Issue Date` (0 mismatches).
- Missing Active/Final `permit_info` Issue Dates are concentrated in Closed code-enforcement / RFS / records-request types that are not issued building permits → **not fillable** from DATA.
- Accela: 1 FILLED (`Closed - Complete` row that had lagged as In Review and already had Permit Issuance / Issued).
- After repair: Active **98/100 (98.0%)**; Final **1,359/1,768 (76.9%)**. Remaining Final gaps lack Issue Date / Issued events in DATA.

### FINAL_DATE

- **Major upstream bug (`permit_info`)**: all 1,127 non-null `FINAL_DATE` values equaled `Permit Details.Expiration Date` (0 matched a true finalization process). Active (18) and Inactive (26) rows incorrectly carried Expiration as `FINAL_DATE`.
- True finalization signals in `Processes And Notes`: Certificate of Occupancy / Completion (CO/CC Issued), processes with “Final” in the name (Building Final, Electrical Final, etc.), or fallback to last approved inspection / changeout / reinspection Ended date.
- Accela: existing finals usually matched Final Inspection Complete; **3** rows were one day earlier than Certificate of Occupancy Final CO Issued → FIXED to CO date. Pending CO Final Inspection Complete as `FINAL_DATE` cleared (status is Active, not Final).
- Repair: **130 FILLED**, **1,131 FIXED** (917 replaced with process dates; 214 cleared incorrect Expiration / non-Final finals).
- After repair: Final **1,125/1,768 (63.6%)**; Active / In Review / Inactive **0%** with `FINAL_DATE`. No remaining `permit_info` `FINAL_DATE` equals Expiration Date.
- Remaining Final gaps (643) are mostly Request for Service / OTC / compliance / records types with no dated finalization process, plus 13 Accela Closed rows without Final Inspection Complete or CO events.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_sarasota_county.py` (`data_repair`)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 3 | 3 | 3 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 1 | 0 | 531 | 530 |
| FINAL_DATE | 130 | 1,131 | 792 | 876 |

`FINAL_DATE` missing rises because incorrect Expiration copies on Final rows without a replacement process date, plus all Expiration copies on non-Final rows, were cleared.

## Not repairable from DATA

- Closed RFS / code compliance / lien search / property records rows with no `Issue Date` → `PERMIT_DATE` stays missing.
- Final rows with empty or admin-only `Processes And Notes` and no Accela Final Inspection / CO event → `FINAL_DATE` stays missing after clearing Expiration.
- Accela Closed rows without dated Certificate or Final Inspection Complete events → `FINAL_DATE` stays missing.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_sarasota_county.py`
- Repaired sample columns: `AGENT_DATA_PATH/sarasota_county_repair/permits_fl_sarasota_county_repaired_sample.parquet`
