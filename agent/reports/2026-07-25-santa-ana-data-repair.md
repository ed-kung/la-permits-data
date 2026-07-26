# Santa Ana (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Santa Ana — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows share one DATA schema (`detail` + `permit`). Status is not stored as a string in DATA; it is encoded by which `detail` date fields are populated (Void → Inactive, Finaled → Final, Expired → Inactive, Issued → Active, Applied-only → In Review). The repair fixed 7 stale statuses (4 Active→Final, 3 In Review→Active), filled 3 missing `PERMIT_DATE` values from Issued, and filled 4 missing `FINAL_DATE` values from Finaled. `FILE_DATE` was already complete and correct. After repair: Final has 100% `FINAL_DATE` and 99.9% `PERMIT_DATE`; Active has 100% `PERMIT_DATE`; non-Final rows have 0% `FINAL_DATE`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Santa Ana, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_santa_ana.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/santa_ana_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `detail_permit` | 2,000 | Portal payload: `detail`, `parcel`, `permit`, `property`, `property_id` |

Canonical fields under `detail`:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | Inferred from which of Void / Finaled / Expired / Issued / Applied are set |
| `FILE_DATE` | `detail.Applied` (fallback: `permit.Applied` `/Date(ms)/`) |
| `PERMIT_DATE` | `detail.Issued` |
| `FINAL_DATE` | `detail.Finaled` |

`detail.Expired` and `detail.Void` are close/cancel stamps, not completion dates.

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,528 · Inactive 337 · Active 92 · In Review 43 · missing 0

`STATUS_ORIGINAL` maps 1:1 onto `STATUS_NORMALIZED` (`finaled`→Final, `expired`/`void`→Inactive, `active`→Active, `in review`→In Review). That original label appears to have been derived from the same date-priority rule, but **7 rows are stale** relative to current `detail` dates:

1. **4 Active with `Finaled` populated** (`40138138`, `101119757`, `101119869`, `101120041`) → should be **Final**.
2. **3 In Review with `Issued` populated** (`30147502`, `101119907`, `20282223`) → should be **Active**.

No missing statuses. Void (45) and Expired (292) correctly stay Inactive even when Issued is present.

**After:** Final 1,532 · Inactive 337 · Active 91 · In Review 40 · missing 0  
Flags: **FILLED 0 · FIXED 7**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` matches `detail.Applied` at calendar-day resolution. No fills or fixes.
- `permit.Applied` (`/Date(ms)/`) agrees with `detail.Applied` where checked.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 149 missing (7.5%). Where present (1,851), always matches `detail.Issued`.

Issues:
1. **3 In Review rows** had Issued but null `PERMIT_DATE` (the same three remapped to Active) → **FILLED**.
2. **2 Final rows** (`10142906`, `10143287`) have empty Issued and Finaled in 2004–2005 → cannot fill from DATA.
3. **104 Inactive** never issued (69 expired + 35 void) → correctly remain missing (not required for Inactive). The other 233 Inactive already carry Issued-based `PERMIT_DATE`.

**After:** missing 146. Active 91/91 (100%) · Final 1,530/1,532 (99.9%).  
Flags: **FILLED 3 · FIXED 0**

### FINAL_DATE

**Before:** 472 missing; all 1,528 Final rows already had `FINAL_DATE` matching `Finaled`. No incorrect values on non-Final rows (the 4 Active-with-Finaled cases had null `FINAL_DATE`).

Repairs:
- After remapping the 4 Active→Final rows, fill `FINAL_DATE` from `detail.Finaled` (**4 FILLED**).

**After:** missing 468. Final 1,532/1,532 (100%); Active / In Review / Inactive all 0%.  
Flags: **FILLED 4 · FIXED 0**

## Repair performance (sample n=2,000)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 0 | 7 | 0 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 3 | 0 | 149 → 146 |
| `FINAL_DATE` | 4 | 0 | 472 → 468 |

Post-repair coverage by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | --- | --- | --- |
| Active | 91 | 100% | 100% | 0% |
| Final | 1,532 | 100% | 99.9% | 100% |
| In Review | 40 | 100% | 0% | 0% |
| Inactive | 337 | 100% | 69.1% | 0% |

## Remaining gaps (not repairable from DATA)

- 2 Final rows with empty `detail.Issued` → `PERMIT_DATE` stays missing.
- 104 never-issued Inactive rows → `PERMIT_DATE` stays missing (expected).
- Inactive / In Review correctly lack `FINAL_DATE`.
