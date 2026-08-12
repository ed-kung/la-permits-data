# Marion County (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Marion County was first. Its DATA is a CDPlus portal payload (`co` / `reviews` / `inspections` / `permit_details`, optional `contractor`). STATUS_NORMALIZED was missing on 3 CWF rows and wrong on 1 COED row still labeled Active from a stale `inspect` original. FILE_DATE and PERMIT_DATE already matched `apply_date` / `issued_date` wherever those sources exist. FINAL_DATE gained 5 fills (one CO upgrade plus four `permit_status=FINAL` rows without a CO, recovered from approved FINAL inspections or `last_inspection_result`), bringing Final coverage to 100%.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Marion County, FL** (1,999 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_marion_county.py` (`data_repair`)

## DATA schema

Every row has top-level `co`, `reviews`, `inspections`, and `permit_details`. Optional `contractor` is present on 1,892 / 1,999 rows.

| INFERRED_SCHEMA (top) | n | permit_status |
| --- | ---: | --- |
| `cdplus_contractor_coed` | 1,587 | COED |
| `cdplus_no_contractor_coed` | 89 | COED |
| `cdplus_contractor_inspect` | 87 | INSPECT |
| `cdplus_contractor_issued` | 84 | ISSUED |
| `cdplus_contractor_cancel` | 45 | CANCEL |
| `cdplus_contractor_apply` | 45 | APPLY |
| *(other status × contractor variants)* | 62 | VOID / EXPIRED / READY / FINAL / CWF / SUSPEND / … |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_details.permit_status` |
| FILE_DATE | `permit_details.apply_date` |
| PERMIT_DATE | `permit_details.issued_date` |
| FINAL_DATE | `co[].issue_date` / `permit_details.co_date`, else approved FINAL inspection `result_date`, else `last_inspection_result` |

Status map: COED / FINAL → Final; ISSUED / INSPECT → Active; APPLY / READY / SUSPEND → In Review; CANCEL / VOID / EXPIRED / CWF → Inactive (CWF = Closed Without Final).

## Field assessments

### STATUS_NORMALIZED

**3 missing** (all `permit_status=CWF`, `STATUS_ORIGINAL=cwf`). Upstream mapped every other CDPlus code but not CWF.

**1 incorrect:** permit `2022050660` has `permit_status=COED` with an issued CO (`co_date=9/21/2023`) but `STATUS_ORIGINAL=inspect` and STATUS_NORMALIZED=Active — original status lagged the portal.

**3 FILLED** (CWF → Inactive); **1 FIXED** (Active → Final). All permit_status values map; none unmapped.

After repair: Final 1,680; Active 174; Inactive 87; In Review 58.

### FILE_DATE

Ideal: populated for all records.

- Before: **0 missing**. All 1,999 equal `apply_date` at day resolution.
- **0 FILLED / 0 FIXED.** Coverage remains 100% for every status.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present, always equaled `issued_date` (no incorrect values).
- **0 FILLED / 0 FIXED.** Active and Final already had full coverage; the COED→Final row already carried `issued_date`.
- Remaining **90 missing** are true nulls in DATA (mostly APPLY / VOID / CANCEL never issued; also some CANCEL without issue stamp). Inactive after repair: 53/87 (60.9%) have PERMIT_DATE. Two SUSPEND (In Review) rows retain issued stamps left untouched.

Coverage after repair: Active 174/174 (100%); Final 1,680/1,680 (100%).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 1,675 Final rows already matched CO dates; **4** `permit_status=FINAL` rows had no `co` / `co_date` (FINAL_DATE null); the mislabeled COED Active row also lacked FINAL_DATE despite a CO.
- **5 FILLED:**
  - `2022050660` from CO `issue_date` after status FIXED to Final
  - three FINAL rows from approved FINAL inspection `result_date`
  - one FINAL row (`2018011561`, fire-marshal closeout only) from `last_inspection_result`
- **0 FIXED** (no wrong non-null dates; no spurious non-Final FINAL_DATE to clear).
- After repair: Final 1,680/1,680 (100%); other statuses 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 1 | 3 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 90 → 90 |
| FINAL_DATE | 5 | 0 | 324 → 319 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_marion_county.py`
- Repaired sample parquet: `AGENT_DATA_PATH/marion_county_repaired_sample.parquet`
