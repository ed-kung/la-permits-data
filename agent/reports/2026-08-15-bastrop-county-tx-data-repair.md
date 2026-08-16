# Bastrop County (TX) data repair — STATUS_NORMALIZED and dates

**Summary:** Among TX sample jurisdictions ordered by name, Bastrop County is the first without an existing repair script (Abilene through Austin already covered). DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`). Upstream left 34 `Waiting on Client` / `Waiting on Client - Floodplain` rows with null `STATUS_NORMALIZED`; repair filled them to In Review. `FILE_DATE` already matched `DateCreated` on every row. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` (193,630 rows). Walking `(JURISDICTION, STATE)` alphabetically, existing TX scripts cover Abilene, Allen, Anna, Arlington, Austin, Dallas, El Paso, Fort Worth, Harris County, Houston, and San Antonio. **Bastrop County** is the first gap → `agent/scripts/tx/data_repair_tx_bastrop_county.py`.

Sample size: **2,000** Bastrop County records.

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,934 | Full MGO key set including `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 66 | Same keys without `PaymentProcessorModule` |

Repair logic uses `ProjectStatus`, `DateCreated`, and `DateIssued` in both variants.

## Field assessment (before repair)

### STATUS_NORMALIZED

| ProjectStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Issued (Construction) | 1,021 | Active | Correct |
| Pending (Under Review) | 881 | In Review | Correct |
| Closed/Completed | 64 | Final | Correct |
| Waiting on Client | 30 | null | Incorrectly missing → In Review |
| Waiting on Client - Floodplain | 4 | null | Incorrectly missing → In Review |

No incorrect non-null statuses relative to `ProjectStatus`. Reason for nulls: upstream status mapper did not cover the “waiting on client” portal values.

### FILE_DATE

- Missing: **0 / 2,000**
- All values match `DateCreated` at calendar-day resolution
- No fill or fix needed

### PERMIT_DATE

- Present: **0 / 2,000**
- Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row
- No alternate issuance stamp in DATA (no placard/receipt filenames, empty inspection lists)
- Active/Final coverage remains 0% — not fillable from this extract
- Script will fill from a real `DateIssued` if present in future extracts

### FINAL_DATE

- Present: **0 / 2,000** (including all 64 Final rows)
- `DateUpdated` is always the same `.NET` sentinel; no finaled / completion / CO field exists
- Not fillable from DATA

## Repair behavior

Canonical mappings:

- `ProjectStatus` → `STATUS_NORMALIZED` (including Waiting on Client* → In Review)
- `DateCreated` → `FILE_DATE`
- `DateIssued` → `PERMIT_DATE` when not sentinel (never in sample)
- FINAL_DATE left missing for Final; cleared only if a non-Final row carried one (none in sample)

Flags: `FILLED` for former missings; `FIXED` for corrected or cleared values. `INFERRED_SCHEMA` set per row.

## Performance (after repair)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 34 | 0 | 34 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Status distribution after: Active 1,021, In Review 915, Final 64 (no nulls, no Inactive).

Date coverage after repair:

- FILE_DATE overall: 2,000 / 2,000 (100%)
- Active/Final PERMIT_DATE: 0 / 1,085 (0%) — DateIssued not published in this extract
- Final FINAL_DATE: 0 / 64 (0%) — no completion timestamp in DATA
- Date-order violations: none

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_bastrop_county.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_tx_bastrop_county_repaired.parquet`
