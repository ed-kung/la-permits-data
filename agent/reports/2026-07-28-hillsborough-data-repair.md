# Hillsborough (CA) data repair

**Summary:** Assessed Hillsborough's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_hillsborough.py`. Every row had missing `STATUS_NORMALIZED`; `permit_info` status/issued/approved/finaled fields are blank, so repair uses `search_data` workflow dates (and VOID-like `Description` text). Filled 1,997 statuses, 1,958 FILE_DATEs, 1,809 PERMIT_DATEs, and 1,548 FINAL_DATEs. After repair: FILE_DATE 99.5%; Active PERMIT_DATE 100%; Final PERMIT_DATE 99.7% / FINAL_DATE 100%. Remaining gaps are empty-date shells and Final rows with neither Issued nor Approved.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Hillsborough, CA**.

## DATA schema

All 2,000 rows have DATA. Top-level keys are always `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data` (fees/contacts/inspections/site_info are empty). Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `search_short_issued_finaled` | 1,543 | Applied/Issued/Approved/Finaled keys; Issued+Finaled present |
| `search_short_issued` | 246 | Issued present, Finaled blank |
| `search_short_applied_only` | 117 | Only Applied |
| `search_short_approved_only` | 35 | Approved, no Issued/Finaled |
| `search_long_applied_only` | 32 | Application Date / Issued Date / Finaled Date keys; only Applied |
| `search_short_finaled_only` | 17 | Finaled, no Issued |
| `search_short_empty_dates` | 10 | No usable workflow dates |

Canonical mappings from DATA:

- Dates + VOID-like `search_data.Description` → `STATUS_NORMALIZED` (`PermitStatus` always blank)
- `search_data.Applied` / `Application Date` / `permit_info.PermitAppliedDate` → `FILE_DATE`
- `search_data.Issued` / `Issued Date` (fallback `Approved`) → `PERMIT_DATE`
- `search_data.Finaled` / `Finaled Date` → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: missing 2,000 / 2,000. Upstream left status null because `PermitStatus` is empty on every row.

Inference rules:

1. **VOID / cancel / withdraw / deny / abandon / reuse / test** in Description → Inactive (77)
2. **Finaled present** → Final (1,548)
3. **Issued or Approved present** → Active (265)
4. **Applied only** → In Review (107)
5. **Empty-date shells with blank Description** (3) → left missing

### FILE_DATE

Before: 32 present (all on `search_long` rows via `PermitAppliedDate`); 1,968 missing. The 32 already matched Applied. Filled 1,958 from Applied. Remaining 10 are empty-date shells with no Applied value. No incorrect FILE_DATE values to overwrite.

### PERMIT_DATE

Before: all missing. Filled from Issued (fallback Approved) for Active/Final. After repair: Active 265/265; Final 1,544/1,548. The 4 Final gaps are `search_short_finaled_only` rows with neither Issued nor Approved (encroachment / demo / PW shells). No incorrect values to overwrite.

### FINAL_DATE

Before: all missing. Filled from Finaled for Final rows → 1,548/1,548 (100%). VOID shells that carry Finaled stamps stay Inactive and do not receive FINAL_DATE (close/void stamp, not permit finaled). No spurious FINAL_DATE on non-Final rows in the source.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 1,997 | 0 | 2,000 → 3 |
| FILE_DATE | 1,958 | 0 | 1,968 → 10 |
| PERMIT_DATE | 1,809 | 0 | 2,000 → 191 |
| FINAL_DATE | 1,548 | 0 | 2,000 → 452 |

After repair coverage:

| Status | N | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- | --- |
| Active | 265 | 265 / 265 (100%) | 265 / 265 (100%) | 0 / 265 |
| Final | 1,548 | 1,548 / 1,548 (100%) | 1,544 / 1,548 (99.7%) | 1,548 / 1,548 (100%) |
| In Review | 107 | 107 / 107 (100%) | 0 / 107 | 0 / 107 |
| Inactive | 77 | 70 / 77 (90.9%) | 0 / 77 | 0 / 77 |
| (null) | 3 | 0 / 3 | 0 / 3 | 0 / 3 |

Overall FILE_DATE: 1,990 / 2,000 (99.5%). Chronology: 0 PERMIT&lt;FILE inversions; 1 FINAL&lt;PERMIT inversion present in source DATA and left as-is.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_hillsborough.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_hillsborough_repaired.parquet`
