# Fremont (CA) data repair

**Summary:** Among CA sample jurisdictions in first-seen order, Fremont was the first `(JURISDICTION, STATE)` pair without a repair script. Its DATA JSON is an Accela Citizen Access payload (`accela_full` / `accela_basic`). `FILE_DATE` already matched `search_data.Date` / `DATA.date` for all 2,001 rows. Status repair fixed 97 incorrect labels: 67 `Revision Issued` rows labeled In Review → Active, 29 `UNK` historical shells incorrectly labeled Final → cleared, and 1 lagged `Issued` row with Inspections Finaled → Final. `PERMIT_DATE` gained 171 fills (mostly Application Submittal / Ready to Issue Issued events) and cleared 2 spurious Ready to Issue dates. `FINAL_DATE` was the main win: 851 Final gaps filled from Inspections Finaled*, Final Admin Closed/Archive, or non-migration Final inspections; Final coverage after repair is 99.4% (1,152 / 1,159).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Fremont, CA** (2,001 rows) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/ca/data_repair_ca_fremont.py`
- Artifact: `AGENT_DATA_PATH/fremont_repaired_sample.parquet`

## DATA schema

Every record has `date`, `tasks`, `status`, `address`, `details`, `job_value`, `valuation`, `total_fees`, `record_type`, `search_data`, and `more_details`. Canonical fields:

| DATA field | Target column |
| --- | --- |
| `DATA.status` (+ Finaled workflow override) | `STATUS_NORMALIZED` |
| `search_data.Date` / `DATA.date` | `FILE_DATE` |
| `Ready to Issue` / `Issued`\|`Revision Issued` (fallback `Application Submittal` / Issued) | `PERMIT_DATE` |
| `Inspections` / `Finaled*` (fallback Final Admin `Closed`/`Files Archived - Close`; then Pass/DONE `*Final*` inspections) | `FINAL_DATE` |

`INFERRED_SCHEMA` variants (same repair logic):

- `accela_full` — 1,850 rows (has `inspections`; usually also conditions / fees_details / related_records / contacts)
- `accela_basic` — 151 rows (workflow / search fields only; no inspections block)

Status map from `DATA.status`: Finaled/Closed → Final; Issued / Issued - Revision Pending / **Revision Issued** → Active; Expired/Cancelled/Void/Withdrawn → Inactive; Cycle 1–2, Incomplete Submittal, Out to Applicant, Pending Payment, Prep/Ready to Issue*, Received → In Review. `UNK` and blank status are intentionally unmapped.

## Field assessment

### STATUS_NORMALIZED

- **Missing before:** 352 / 2,001 — all `Historical Project` rows with blank `DATA.status` / `STATUS_ORIGINAL`
- **Correctness:** Where `DATA.status` was in the upstream vocabulary, labels mostly matched. Material errors:
  - 67× `Revision Issued` labeled **In Review** — revisions already issued (Ready to Issue / Revision Issued events; 66/67 already had `PERMIT_DATE`) → should be **Active**
  - 29× `UNK` (`Building/Historical/NA/NA`) labeled **Final** with no completion evidence → should be **null**
  - 1× `Issued` (`BLD2020-01164`) still Active while Inspections Finaled + Admin Closed → lagged status → **Final**
- **Repair:** **0 FILLED**, **97 FIXED** · missing after: 381 (352 Historical Project + 29 UNK)
- After: Final 1,159 · Active 201 · Inactive 196 · In Review 64 · null 381

### FILE_DATE

- **Missing:** 0 / 2,001
- **Correctness:** Calendar-day match to `search_data.Date` / `DATA.date` for all rows.
- **Repair:** 0 FILLED, 0 FIXED (already complete)

### PERMIT_DATE

- **Missing before:** 1,667 / 2,001
- **Correctness:** Where both `PERMIT_DATE` and an Issued/Revision Issued event exist (332/334), they match Ready to Issue issuance. Two Ready to Issue (In Review) rows incorrectly used a pre-issuance Ready to Issue / review date as `PERMIT_DATE`.
- **Fillable:** 171 Active/Final gaps — 83 Active (Application Submittal / Issued on OTC-style permits) + 88 Final
- **Repair:** **171 FILLED**, **2 FIXED** (cleared spurious In Review dates) · missing after: 1,498
- Post-repair coverage: Active 99.0% (199/201); Final 24.9% (289/1,159)
- **Not fillable:** 2 Active Issued rows with only Inspections TBD events; ~870 Final rows (mostly older Finaled shells with empty issuance workflow)

### FINAL_DATE

- **Missing before:** 1,700 / 2,001
- **Correctness:** All 301 pre-existing `FINAL_DATE` values matched an Inspections Finaled* event date. Two Final rows used an earlier Finaled event while a later Finaled existed → FIXED to the latest Finaled date. One Active row carried a real Finaled date; status upgrade to Final kept it.
- **Fillable Final gaps:** ~89 from Finaled/Closed task events + ~762 from Final inspections (prefer `999 Permit Final`, skip Accela cutover sentinel `2017-07-01` when a real date exists)
- **Repair:** **851 FILLED**, **2 FIXED** · missing after: 849
- Post-repair: Final 99.4% (1,152 / 1,159); Active / In Review / Inactive all 0%
- **Not fillable:** 7 Final rows — 6 Closed shells with empty tasks/inspections, plus 1 Finaled row whose Final inspections are only Cancelled (`CC`) or migration-stamped

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 97 | 352 | 381 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 171 | 2 | 1,667 | 1,498 |
| FINAL_DATE | 851 | 2 | 1,700 | 849 |

Root causes: (1) upstream mapped `Revision Issued` to In Review and `UNK` to Final; (2) issuance dates for OTC/instant permits live on `Application Submittal` / Issued rather than Ready to Issue, so many Active `PERMIT_DATE` values were left blank; (3) Finaled historical permits often lack workflow events but retain `999 Permit Final` inspection dates that the extract did not promote to `FINAL_DATE`. Remaining Final `PERMIT_DATE` gaps and the 7 Final `FINAL_DATE` gaps reflect empty Accela histories, not mapping bugs. Net Final `FINAL_DATE` coverage rises from ~25% to 99.4%.
