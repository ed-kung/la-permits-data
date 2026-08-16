# Dallas (TX) data repair — STATUS_NORMALIZED and dates

**Summary:** Among TX sample jurisdictions in first-appearance order, Dallas is the first without an existing repair script. Dallas DATA is ~93% legacy permit-portal payloads (`Status` / `Created Date` / `Issued Date` / `Completed Date`) and ~7% Accela Civic Platform records (`status` / `date` / `tasks`). The main defects are 62 status values that are null or disagree with DATA (often because `STATUS_ORIGINAL` lagged behind `Status`), 7 missing `PERMIT_DATE` values where `Issued Date` exists, 30 missing Final completion dates that DATA can supply, and 556 spurious `FINAL_DATE` values on non-Final rows (agency stamps `Completed Date` on cancelled/expired/revoked/null-status cases). After repair, Final rows have 98.8% `FINAL_DATE` coverage and non-Final rows have none.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`. Walking unique `(JURISDICTION, STATE)` in first-appearance order, existing TX scripts cover Austin, Fort Worth, Houston, and San Antonio. **Dallas** is the first gap → `agent/scripts/tx/data_repair_tx_dallas.py`.

Sample size: **1,998** Dallas records.

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Distinguishing keys / shape |
| --- | ---: | --- |
| `legacy_related` | 1,851 | `Status`, dates, `owner`, `related_information` |
| `accela` | 129 | `status`, `date`, `tasks`, `search_data`, … |
| `legacy_parcel` | 13 | legacy dates + `Parcel` (no `related_information`) |
| `legacy_owner` | 5 | legacy dates + `owner` (no `related_information` / `Parcel`) |

Legacy variants share the same status/date fields used for repair. Accela dates come from top-level `date` and task event marks.

## Field assessment (before repair)

### STATUS_NORMALIZED

| Value | n |
| --- | ---: |
| Final | 1,071 |
| Inactive | 413 |
| Active | 224 |
| (null) | 211 |
| In Review | 79 |

**Incorrectly missing (fillable, 11):** `New Web Application`→In Review (3), Accela `Document Received`→In Review (3), `Application About to Expire`→In Review (2), `CO Complete`→Final (1), `Permit Issued`→Active (1), `Permit About to Expire`→Active (1).

**Incorrect non-null (51):** Upstream often kept a stale `STATUS_ORIGINAL` (e.g. `permit issued`) while DATA `Status` had advanced. Examples:

| DATA Status | Was | Should be | n (approx) |
| --- | --- | --- | ---: |
| Work Completed / CO Issued | Active / In Review | Final | 25 |
| Application Cancelled / Permit Expired / Permit Revoked | Active / In Review | Inactive | 21 |
| Permit Issued | In Review | Active | 5 |

**Not fillable (200):** Legacy rows with null `Status` and no usable `STATUS_ORIGINAL` (mostly empty/stub portal records).

### FILE_DATE

- Missing: **29 / 1,998** — all lack `Created Date` / Accela `date` as well
- Present values match `Created Date` (legacy) or `date` (accela) at calendar-day resolution
- No fill or fix needed

### PERMIT_DATE

- Missing: **598**
- Present values match `Issued Date` (legacy) or Permit Issuance→Issued (accela)
- **7** fillable from `Issued Date` (mostly mis-statused Permit Issued / CO Pending / Work Completed rows)
- Remaining Active/Final gaps lack an issuance signal in DATA (esp. Accela Inspection Phase / Closed cases without a Permit Issuance task)

### FINAL_DATE

- Present values match `Completed Date` or Accela `Final Inspection Complete` when both exist
- **Incorrect extras on non-Final:** 556 rows (Application Cancelled, Permit Expired/Revoked, null Status, Accela Inspection Phase with a final-inspection mark) — agency completion stamps are not true Final for our schema
- **Incorrectly missing on Final:** 25 legacy Work Completed/CO Issued rows mislabeled Active (no FINAL stored) + Accela Closed-Approved (4) and TCO Issued (1) with completion task marks

## Repair behavior

Canonical mappings:

- Legacy: `Status` → status; `Created Date` → `FILE_DATE`; `Issued Date` → `PERMIT_DATE`; `Completed Date` → `FINAL_DATE` only when effective status is Final
- Accela: `status` → status; `date` → `FILE_DATE`; Permit Issuance/`Issued` → `PERMIT_DATE`; Inspection/`Final Inspection Complete`, CO/`Final CO Issued`, or Modification Review/`Modification Request Approved` → `FINAL_DATE` only when Final; otherwise clear

Flags: `FILLED` for former missings; `FIXED` for corrected or cleared values. `INFERRED_SCHEMA` set per row.

## Performance (after repair)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 11 | 51 | 211 → 200 |
| FILE_DATE | 0 | 0 | 29 → 29 |
| PERMIT_DATE | 7 | 0 | 598 → 591 |
| FINAL_DATE | 30 | 556 | 388 → 914 |

Status distribution after: Final 1,097, Inactive 434, Active 190, In Review 77, null 200.

Date coverage after repair:

| Rule | Coverage |
| --- | --- |
| FILE_DATE overall | 1,969 / 1,998 (98.5%) |
| PERMIT_DATE on Active | 147 / 190 (77.4%) |
| PERMIT_DATE on Final | 1,076 / 1,097 (98.1%) |
| FINAL_DATE on Final | 1,084 / 1,097 (98.8%) |
| FINAL_DATE on non-Final | 0 |

Remaining Final gaps without `FINAL_DATE` are 13 Accela `Closed - Complete` rows with no completion task mark in `tasks`. Remaining Active/Final `PERMIT_DATE` gaps lack `Issued Date` / Permit Issuance→Issued in DATA.

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_dallas.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_dallas_repaired.parquet`
