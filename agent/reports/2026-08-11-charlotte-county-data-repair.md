# Charlotte County (FL) data repair

Summary: Charlotte County was the first FL sample jurisdiction without a repair script after Jacksonville, Lee County, Sarasota County, Osceola County, and Orlando. Accela Citizen Access payloads expose status under `DATA.status` and dates under `DATA.date`, Permit Issuance / Finaled / End of Process task events, and inspection Status Dates. The repair remaps 85 statuses (29 FILLED, 56 FIXED) where `STATUS_ORIGINAL` lagged Accela or upstream left statuses unmapped/mis-mapped, fills 93 missing `FILE_DATE` values from parseable Accela dates or intake events, adds 8 missing `PERMIT_DATE` values from Issued workflow events, and recovers **1,520** of 1,657 Final rows' missing `FINAL_DATE` (upstream was 100% null). Remaining gaps are mostly empty-status POS/damage rows, permit-number tokens in `DATA.date`, and Closed code-enforcement / shell records with no issuance or finalization history.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Charlotte County, FL**
- Sample size: **1,997** records
- Script: `agent/scripts/fl/data_repair_fl_charlotte_county.py` (`data_repair`)

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `accela_full` | 1,201 | Accela payload with `inspections` and at least one dated task event |
| `accela_basic` | 643 | Dated task events without an `inspections` array |
| `accela_shell` | 153 | Tasks present but no dated events (thin / legacy histories) |

Canonical field sources:

- `DATA.status` → `STATUS_NORMALIZED`
- `DATA.date` / `search_data.Date` (else earliest Intake / Sufficiency event) → `FILE_DATE`
- Earliest Permit Issuance / Permit Issued / Issuance Marked as Issued (or Issuance Complete) → `PERMIT_DATE`
- Finaled Finaled/Closed/CO; else End of Process Closed; else Response Completed; else Final inspection Status Date → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,647; Active 145; In Review 82; Inactive 74; missing 49.
- Upstream `STATUS_NORMALIZED` follows `STATUS_ORIGINAL`, which lags `DATA.status` on **24** rows (e.g. ORIG=`permit issued` / `issued` while Accela shows `Closed` / `Expired` / `C of O Issued`).
- Missing statuses were unmapped Accela codes (`Founded`, `Application Insufficient`, `SPR Approved`, lien-closed variants, hearing/admin codes) plus **20** rows with empty `DATA.status`.
- Additional mis-maps vs Accela meaning:
  - `Property Registered` (vacant-property program, still open) stored as Final → should be Active
  - `SUSPEND` stored as In Review → Inactive
  - `Notice` / `Application Complete` stored as Final → In Review
  - `Assessment Complete` stored as In Review → Final
- Repair using `DATA.status`:
  - **29 FILLED** (Founded, Application Insufficient, SPR Approved, Closed-Lien*, Property Occupied/Sold, hearing/admin codes, etc.)
  - **56 FIXED** — mainly Property Registered Final→Active (13), SUSPEND In Review→Inactive (9), lagged Closed Active/In Review/Inactive→Final (13), Assessment Complete→Final (6), Expired lags→Inactive (6), Permit Issued lags→Active (4), Notice/Application Complete→In Review (3), others (2)
- After repair: Final 1,657; Active 153; Inactive 88; In Review 79; missing **20**.
- Remaining missing: all 20 have empty `DATA.status` (mostly CE Damage Assessment and POS stubs) → not fillable from DATA.

### FILE_DATE

- Before: 104 missing (5.2%). Among non-null values, **1,893 / 1,893** already matched parseable `DATA.date` at day resolution (0 mismatches).
- **33** rows store a permit-number-like token in `DATA.date` (8+ digits) with no `search_data.Date`; **71** missing FILE rows had a normal Accela date available.
- Repair: **93 FILLED** (71 from `DATA.date` / search Date; 22 from Intake / Sufficiency events when `DATA.date` was a non-date token), **0 FIXED**.
- After: **11 missing** — all Closed trade permits with numeric `DATA.date` tokens and no dated intake event.

### PERMIT_DATE

- Before: 476 missing (23.8%). Among Active/Final, coverage was already high for true building permits (Active 99.3%; Final 80.8%).
- Issued marks on `Permit Issuance` / `Permit Issued` / `Issuance` match existing `PERMIT_DATE` on **1,504** rows; vacant-property `Issuance` Complete dates also match existing values.
- Repair: **8 FILLED** for Active/Final rows with an Issued event but null permit; **0 FIXED**.
- After repair: Active **149/153 (97.4%)**; Final **1,333/1,657 (80.4%)**.
- Remaining Active/Final gaps (**328**): mostly Closed code-enforcement / research-request / damage-assessment rows with no issuance workflow, plus COED / shell building rows with empty task events. Not true issued building permits in Accela history.

### FINAL_DATE

- Before: **1,997 missing (100%)**. Upstream never populated finalization for this jurisdiction.
- Strong signals in DATA: Finaled marked Finaled (682) / Closed (562) / C of O Issued (50) / Certificate of Occupancy Issued (34); End of Process Closed (366); Response Completed on research requests (56); Final-titled inspection Status Dates.
- Repair: **1,520 FILLED**, **0 FIXED** (nothing to overwrite).
- After: Final **1,520/1,657 (91.7%)**; Active / In Review / Inactive have **0** (no spurious finals).
- Remaining Final gaps (**137**): mostly `accela_shell` Closed rows (111) with empty event histories, plus COED / Assessment Complete / Compliant cases without dated Finaled / EOP / inspection closeout.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 29 | 56 | 49 | 20 |
| FILE_DATE | 93 | 0 | 104 | 11 |
| PERMIT_DATE | 8 | 0 | 476 | 468 |
| FINAL_DATE | 1,520 | 0 | 1,997 | 477 |

Coverage after repair (share non-null):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 153 | 100.0% | 97.4% | 0.0% |
| Final | 1,657 | 99.3% | 80.4% | 91.7% |
| In Review | 79 | 100.0% | 1.3% | 0.0% |
| Inactive | 88 | 100.0% | 52.3% | 0.0% |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_charlotte_county.py`
- No derived datasets written under `AGENT_DATA_PATH` (CLI prints stats only).
