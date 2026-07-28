# Placer County (CA) data repair

**Summary:** Placer County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script (1,999 rows). DATA is an Accela Citizen Access scrape with task-event dates. Main defects: stale `STATUS_ORIGINAL` vs live `DATA.status` (especially 611 `DONE` shells labeled In Review, plus Construction Complete / Expired / Issued mismatches); Accela `1900-01-01` FILE_DATE placeholders; missing `PERMIT_DATE` on Active/Final despite Issued task marks; a handful of Finals missing `FINAL_DATE` despite Construction Complete / Final Pass evidence. Script: `agent/scripts/ca/data_repair_ca_placer_county.py`. Artifact: `$AGENT_DATA_PATH/processed_data/permits_ca_placer_county_repaired.parquet`.

## Jurisdiction selection

Went down first-seen `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`. Existing scripts live under `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing pair: **Placer County, CA**.

## DATA schema

Accela Citizen Access payloads. Task event keys often have leading/trailing spaces (`Marked as `, ` on `).

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| accela_no_date | 1,167 | Full scrape without top-level `date`; FILE_DATE from `search_data.Date` |
| empty_tasks | 717 | Status/tasks present but no dated events (legacy DONE + sparse shells) |
| accela_with_date | 105 | Top-level `date` + fees/inspections, with dated workflow events |
| accela_partial | 8 | Missing fees and/or contacts |
| search_data_only | 2 | TMP shells with blank Status |

Canonical sources:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status` (else `search_data.Status`) |
| FILE_DATE | `DATA.date` / `search_data.Date` (reject year 1900; else earliest `fees_details.Date`) |
| PERMIT_DATE | Process for Issuance / Ready to Issue / Issue Status → `Issued` (fallback: Plan Check / Plan Review → `Issued`) |
| FINAL_DATE | Inspections / Construction Complete (latest); else Final*-titled Final Pass inspection `Status Date` |

## Field assessment

### STATUS_NORMALIZED

Pre-repair: Final 851 / In Review 732 / Inactive 216 / Active 198 / missing 2.

Upstream mapped `STATUS_ORIGINAL` (lowercased `DATA.status` at scrape time). Live `DATA.status` disagrees on 34 rows, and the large `DONE` cohort is systematically wrong:

1. **DONE → In Review (611):** legacy Accela finished shells with empty task events. Remapped to **Final** (same class as FINISHED / Closed-Complete in other Accela counties). No issuance or finaling timestamps exist in DATA for these rows.
2. **Construction Complete labeled Active (15):** stale `STATUS_ORIGINAL=issued` → FIXED to **Final**; Construction Complete events supply `FINAL_DATE`.
3. **Expired labeled Active (8):** stale issued → FIXED to **Inactive**.
4. **Issued / Final Processing labeled In Review (7):** FIXED to **Active**.
5. **Expired labeled In Review (1):** FIXED to **Inactive**.
6. **2 search_data-only TMP shells** with blank Status → FILLED **In Review**.

### FILE_DATE

Pre-repair: 0 nulls, but **319 rows carry Accela sentinel `1900-01-01`** (also in `DATA.date` / `search_data.Date`). Only 2 of those have usable `fees_details.Date` values (2004-07-21, 2005-03-31) → FIXED from fees. Remaining 317 cleared to null (FIXED). Non-sentinel FILE_DATE already matched `DATA.date` or `search_data.Date`.

Coverage after repair: **1,682 / 1,999 (84.1%)**.

### PERMIT_DATE

Ideal: populate for Active and Final. When present, values usually matched an Issued task mark or same-day Application Submittal Complete (Issued same calendar day).

Issues repaired:

- **214 FILLED** from Issued marks (205 Final with Plan Check / Issued; 4 Active; plus remapped Construction Complete rows that already had Issued).
- **14 FIXED** where PERMIT_DATE was Process for Issuance / Ready to Issue and a later Issued event existed.

Remaining gaps: 8 Active (Final Processing with Issuance TBD, Issued shells without dated Issued) and 34 non-DONE Final (Construction Complete with only an Inspections event, no Issued mark). All 611 DONE Finals lack issuance events.

### FINAL_DATE

Ideal: populate for Final only.

- **16 FILLED:** 15 Active→Final Construction Complete remaps + 1 Final Pass reroof inspection.
- **10 FIXED** to a later Construction Complete stamp when multiple events existed.
- **1 FIXED** clear: spurious FINAL_DATE on a Received / In Review row (Inspection Approved is not finaling).

Among non-DONE Finals after repair: **855 / 866 (98.7%)** have FINAL_DATE. DONE Finals contribute 0.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_placer_county.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 2 | 642 | 2 | 0 |
| FILE_DATE | 0 | 319 | 0 | 317 |
| PERMIT_DATE | 214 | 14 | 1,102 | 888 |
| FINAL_DATE | 16 | 11 | 1,159 | 1,144 |

Status after repair: Final 1,477 / Inactive 225 / Active 182 / In Review 115 (no nulls).

Coverage after repair:

- FILE_DATE: 1,682 / 1,999 (84.1%)
- PERMIT_DATE: Active 174/182 (95.6%); Final overall 832/1,477 (56.3%); Final excluding DONE 832/866 (96.1%)
- FINAL_DATE: Final overall 855/1,477 (57.9%); Final excluding DONE 855/866 (98.7%); 0 on non-Final

## Remaining gaps (not repairable from DATA)

- **FILE_DATE (317):** Accela 1900 placeholders with no fee or other application date.
- **PERMIT_DATE:** 8 Active without dated Issued; 34 Construction Complete Finals with only Inspections / Construction Complete; all 611 DONE Finals.
- **FINAL_DATE:** ~11 non-DONE Finals with Inspections marked TBD and no Final Pass inspection; all 611 DONE Finals.
