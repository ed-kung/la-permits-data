# Twentynine Palms (CA) data repair

**Summary:** Assessed Twentynine Palms' 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_twentynine_palms.py`. DATA is a flat scraped-table JSON with four key-naming variants and frequent column-shift corruption in `Issue Date`. The repair fills 20 missing statuses and fixes 149 stale ones (mostly In Plan Review shells with real issue stamps promoted to Active), and fills 2 missing PERMIT_DATEs. FILE_DATE and FINAL_DATE cannot be repaired — DATA has neither an application nor a finaled/completion field. After repair, Active has 100% PERMIT_DATE; Final remains at 83.8% because 216 Closed shells store work-description text in `Issue Date`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Twentynine Palms, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `compact_keys_with_work` | 1,095 | `Address` / `Permit#` + `Work Description` |
| `spaced_keys_with_work` | 509 | `Address ` / `Permit #` + `Work Description` |
| `compact_keys` | 308 | `Address` / `Permit#` (no work description) |
| `spaced_keys` | 88 | `Address ` / `Permit #` (no work description) |

Canonical mappings from DATA:

- `Status` → `STATUS_NORMALIZED` (with Issue Date override)
- `Issue Date` → `PERMIT_DATE` (when parseable as a date)
- No application / submittal field → `FILE_DATE` unrepairable
- No finaled / completion / signoff field → `FINAL_DATE` unrepairable

`Issue Date` is parseable for 1,605 / 1,998 rows that have the key. The remaining ~393 values are work-description or subtype text (e.g. `Reroof`, `Gas Line`, `Single Family Residence`) from shifted table columns.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,326 / Active 325 / In Review 268 / Inactive 59 / missing 22.

Issues:

1. **Missing (22):** 10 `Changes Required`, 8 `Payment Needed`, 1 `Issued` (STATUS_ORIGINAL was payment needed), 1 date-in-Status corruption (`03/03/2022`), 1 `Commercial - Motel` (subtype text in Status), 1 fully blank Status shell.
2. **Incorrect / stale (149 after repair):**
   - 144 `In Plan Review` / `On Hold` rows with a parseable Issue Date left In Review → Active.
   - 5 `Final` / `Closed` shells left Active → Final.
   - Mapped nulls: 17 → In Review (`Changes Required` / `Payment Needed` without Issue Date), 3 → Active (`Issued` / `Payment Needed` with Issue Date / date recovered from Status).

Repair performance: **20 FILLED, 149 FIXED**; missing after: **2** (`Status=None` and `Commercial - Motel` — no usable label or date).

After: Final 1,331 / Active 467 / In Review 141 / Inactive 59 / missing 2.

### FILE_DATE

Before: **2,000 / 2,000 missing**. DATA contains no application or submittal date.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 0%.

### PERMIT_DATE

Before: 396 missing. Where both present, PERMIT_DATE matches parseable `Issue Date` exactly (1,604 / 1,604; 0 mismatches).

Issues:

1. One `Issued` row with Issue Date `05/22/2024` had null PERMIT_DATE → FILLED.
2. One column-shift row with Status `03/03/2022` and Issue Date holding work-description text → Issue Date recovered from Status → FILLED (and status set Active).
3. 216 `Closed` Final shells have non-date Issue Date text → PERMIT_DATE stays missing (not in DATA).

Repair: **2 FILLED, 0 FIXED**. Missing after: **394**.

Active coverage after repair: **467 / 467 (100%)**. Final: **1,115 / 1,331 (83.8%)**. In Review: **0 / 141 (0%)** — as expected (no issuance stamp).

### FINAL_DATE

Before: **2,000 / 2,000 missing**. DATA has no finaled, completion, or signoff date.

Repair: **0 FILLED, 0 FIXED**. All 1,331 Final rows remain without FINAL_DATE — not recoverable from DATA.

## Repair script

`agent/scripts/ca/data_repair_ca_twentynine_palms.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels (Void / Expired / Withdrawn) sticky; Closed / Final → Final; else parseable Issue Date (including date recovered from corrupted Status) → Active; else Status map (`Issued` → Active; `In Plan Review` / `Under Review` / `Changes Required` / `Payment Needed` / `Online Application Received` / `On Hold` → In Review).

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 20 | 149 | 22 | 2 |
| FILE_DATE | 0 | 0 | 2,000 | 2,000 |
| PERMIT_DATE | 2 | 0 | 396 | 394 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

### Ideal-coverage gaps remaining

| Gap | N |
| --- | --- |
| Any missing FILE_DATE | 2,000 |
| Active/Final missing PERMIT_DATE | 216 (all Closed with non-date Issue Date) |
| Final missing FINAL_DATE | 1,331 |
| Missing STATUS_NORMALIZED | 2 |

### Artifact

`AGENT_DATA_PATH/repaired/permits_ca_twentynine_palms_repaired.parquet`
