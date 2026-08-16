# El Paso (TX) data repair — STATUS_NORMALIZED and dates

**Summary:** Among TX sample jurisdictions in first-appearance order, El Paso is the first without an existing repair script. DATA is Accela Civic Platform (`status` / `date` / `tasks`), mostly full payloads with inspections/contacts. Main defects: 28 null statuses (7 unmapped agency values + 21 blank), `PERMIT_DATE` often taken from Issue Certificate instead of Issue Issued (108 rows), and almost all Final rows missing `FINAL_DATE` despite Close/certificate/inspection signals (only 2/1,122 had a final date). After repair, 11 statuses are filled, 112 permit dates are corrected or filled, and Final `FINAL_DATE` coverage rises from 0.2% to 74.9%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`. Walking unique `(JURISDICTION, STATE)` in first-appearance order, existing TX scripts cover Austin, Fort Worth, Houston, San Antonio, Dallas, and Harris County. **El Paso** is the first gap → `agent/scripts/tx/data_repair_tx_el_paso.py`.

Sample size: **2,000** El Paso records.

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Distinguishing keys / shape |
| --- | ---: | --- |
| `accela_full` | 1,983 | Accela payload with `inspections`, `contacts`, `fees_details`, etc. |
| `accela_lean` | 17 | Same core (`status`, `date`, `tasks`) without inspections/contacts/fees |

Repair logic uses `status`, `date`, and Accela `tasks` / event marks in both variants.

## Field assessment (before repair)

### STATUS_NORMALIZED

Upstream mapping from `DATA.status` is mostly correct:

| Agency status | n | STATUS_NORMALIZED |
| --- | ---: | --- |
| Closed / Final / Issue Certificate / TCO Issued | 1,122 | Final |
| Inspection / Issued | 578 | Active |
| Expired / Cancelled / Void | 243 | Inactive |
| In Review / Hold for Corrections / Out for Corrections / Pending Review / Pending Issuance / Ready to Issue | 29 | In Review |

**Incorrectly missing (28):**

| DATA.status | n | Expected |
| --- | ---: | --- |
| *(null)* | 21 | Final for 4 rows with Close task; otherwise not inferable |
| FRZ | 2 | In Review (flood-zone style label; no further workflow signal) |
| Non-Compliant Resubmit | 2 | In Review |
| NFZ | 1 | In Review |
| Approved - Pending Contractor | 1 | In Review |
| Audit Review Complied | 1 | Final |

No incorrect non-null statuses found relative to the mapped agency values.

### FILE_DATE

- Missing: **0 / 2,000**
- All values match top-level `date` at calendar-day resolution (also matches `search_data.Date` for 1,998)
- No fill or fix needed

### PERMIT_DATE

- Present: **1,496**; missing: **504**
- **1,382** match earliest `Issue` task marked `Issued`
- **108** incorrectly use `Issue Certificate` Issued when an earlier `Issue` Issued exists (upstream preferred certificate/CO date over permit issuance) → should be FIXED to Issue Issued
- **5** correctly use Issue Certificate Issued as fallback (no Issue Issued event)
- **4** Active/Final rows missing `PERMIT_DATE` despite Issue Issued in DATA → FILLED
- Remaining gaps: no Issue / Issue Certificate Issued event in DATA (especially older Closed / Inspection lean records)

Ideal coverage before (Active + Final): Active 449/578 (77.7%), Final 853/1,122 (76.0%).

### FINAL_DATE

- Present: **2** (both Final); missing: **1,998**
- **0** spurious finals on non-Final rows
- **791** Final rows have Close task marked Closed/Close but no `FINAL_DATE` — upstream never copied the Close event date
- Additional Final signals available: Issue Certificate Issued; Inspection marked Closed; Inspection Issued/Approved TCO
- **~282** Closed Final rows still lack any of those task signals (often older records); inspection list `Status Date` values are frequently sentinel (~year 2000) and were not used

## Repair behavior

Canonical mappings:

- `status` → `STATUS_NORMALIZED` (plus Close/Issue inference when status is blank)
- `date` → `FILE_DATE`
- `Issue` Issued → `PERMIT_DATE` (fallback: `Issue Certificate` Issued)
- Close Closed/Close → `FINAL_DATE` for Final only (fallbacks: Issue Certificate Issued; Inspection Closed; Inspection TCO marks); clear on non-Final

Flags: `FILLED` for former missings; `FIXED` for corrected values. `INFERRED_SCHEMA` set per row.

## Performance (after repair)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 11 | 0 | 28 → 17 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 4 | 108 | 504 → 500 |
| FINAL_DATE | 842 | 0 | 1,998 → 1,156 |

Status distribution after: Final 1,127, Active 578, Inactive 243, In Review 35, null 17.

Date coverage after repair:

| Rule | Coverage |
| --- | --- |
| FILE_DATE overall | 2,000 / 2,000 (100%) |
| PERMIT_DATE on Active | 452 / 578 (78.2%) |
| PERMIT_DATE on Final | 854 / 1,127 (75.8%) |
| FINAL_DATE on Final | 844 / 1,127 (74.9%) |
| FINAL_DATE on non-Final | 0 / 856 |

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_el_paso.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_el_paso_repaired.parquet`
