# Bradenton (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (sorted `(JURISDICTION, STATE)` order) was Bradenton (1,999 records). DATA splits into `city_app` (1,653), `accela` (343), and `search_only` (3). STATUS_NORMALIZED: 1,668 FILLED + 4 FIXED (nulls 1,671→3). FILE_DATE already complete and correct (0 changes). PERMIT_DATE: 148 FILLED from Accela Permit Issuance events (gaps 484→336). FINAL_DATE: 1,272 FILLED from PASS inspections / Certificate of Completion (was 100% missing; Final coverage 92.6%).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Bradenton, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/fl/data_repair_fl_bradenton.py`
- Artifact: `AGENT_DATA_PATH/bradenton_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `city_app` | 1,653 | `app` / `permit` / `inspection_list` / `fees` / `init_info` / `permit_list` |
| `accela` | 343 | Accela Citizen Access: `status` / `date` / `tasks` / `search_data` |
| `search_only` | 3 | Only `search_data` (temp `25TMP-*` shells; blank Status) |

## Field assessment

### STATUS_NORMALIZED

- Before: null 1,671; Active 158; Final 114; Inactive 45; In Review 11.
- Root cause: `city_app` rows almost never received an upstream mapping despite clear `app.Status` values (`COMPLETE / CLOSED`, `ACTIVE / ISSUED`, …). Accela left `Documents Received` / `More Info Required` null; `Admin Closed` was incorrectly labeled Final.
- Canonical rule: map `app.Status` (city_app) or top-level `status` (accela). Unissued Active rows with Permit Status `REVIEWING`/`FEE` → In Review. `Admin Closed` → Inactive. `Approved` license registrations stay Active.
- **1,668 FILLED + 4 FIXED** (3 Admin Closed Final→Inactive; 1 Active→In Review on unissued `active / issued`).
- After: Final 1,374; Active 371; Inactive 135; In Review 116; null 3 (`search_only` temps).

### FILE_DATE

- Ideal: populated for all records.
- Before: 0 missing. All values match `Application Received Date` (city_app) or `date` / `search_data.Date` (accela).
- **0 FILLED + 0 FIXED.** Coverage remains 100% across all statuses.

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Before: 484 missing — all 343 Accela rows lacked issuance dates; city_app blanks are genuine (no `Issued Date`, typically REVIEWING/FEE/WITHDRAWN).
- Source: city_app `permit.Issued Date` (already correct when present); Accela earliest Permit Issuance event marked `Permit Issued`.
- **148 FILLED + 0 FIXED** (Accela Closed-CC Issued / Issued / Completed / Admin-remapped cases with issuance events; Admin Closed no longer count as Final so only Active/Final fills apply).
- After: Active 267/371 (72.0% — 104 Accela `Approved` license registrations have no Permit Issuance task); Final 1,335/1,374 (97.2%).

### FINAL_DATE

- Ideal: populated for Final.
- Before: **1,999 / 1,999 missing.**
- Source: city_app latest inspection `PASS` date; for `CERTIFICATE OF COMPLETION` permit types, `Issued Date` is treated as signoff (`max(PASS, Issued)`). Accela: Certificate Issuance `Certificate of Completion`, else Final Inspection `Approved`.
- **1,272 FILLED + 0 FIXED.**
- Not repairable: 98 city_app Final rows with no dated PASS; 4 Accela `Completed` license rows without CC/FI events.
- After: Final 1,272/1,374 (92.6%); non-Final FINAL_DATE all null. PERMIT>FINAL inversions: 15 (city_app only; PASS predates Issued on a few trade permits).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1,668 | 4 | 1,671 → 3 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 148 | 0 | 484 → 336 |
| FINAL_DATE | 1,272 | 0 | 1,999 → 727 |

Ideal-field coverage after repair (among non-null STATUS_NORMALIZED):

- FILE_DATE: 100% Active / Final / In Review / Inactive
- PERMIT_DATE: 72.0% Active; 97.2% Final; 7.8% In Review; 38.5% Inactive
- FINAL_DATE: 92.6% Final; 0% non-Final

Post-repair checks: STATUS nulls limited to 3 temp shells; FILE_DATE unchanged and fully populated; Accela issuance/final task dates recovered for Closed-CC Issued / Issued; city_app Final mostly dated from PASS inspections; Admin Closed no longer counted as Final.

## Artifacts

- `agent/scripts/fl/data_repair_fl_bradenton.py`
- `AGENT_DATA_PATH/bradenton_repaired_sample.parquet`
