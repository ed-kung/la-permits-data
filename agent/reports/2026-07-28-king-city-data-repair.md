# King City (CA) data repair

**Summary:** King City (CA) was the first sample jurisdiction lacking a repair script (2,000 rows). DATA is a flat tabular export with Status / Issue Date only — no apply or finaling timestamps. Upstream STATUS_ORIGINAL lagged live Status on 7 rows and left 25 statuses unmapped; repair fills/fixes 31 statuses (1 `SOLAR APP` left null). FILE_DATE and FINAL_DATE remain fully missing (no source in DATA). PERMIT_DATE fills 3 Active/Final rows from valid Issue Date / shifted Status dates; ~403 Active/Final rows still lack a parseable issuance stamp because Issue Date often holds Work Description text.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order (accent-normalized city slugs). The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **King City, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Flat open-data keys: `Status`, `Address` or `Address `, `Permit#` or `Permit #`, `Permit Type`, `Sub Type`, optional `Issue Date`, optional `Work Description`.

| Schema | n | Description |
| --- | ---: | --- |
| `tabular_compact` | 1,017 | `Address` / `Permit#` + Issue Date + Work Description |
| `tabular_spaced` | 576 | `Address ` / `Permit #` + Issue Date + WD |
| `tabular_compact_no_wd` | 261 | Compact headers; Issue Date present, no WD |
| `tabular_spaced_no_wd` | 127 | Spaced headers; Issue Date present, no WD |
| `tabular_compact_no_issue` | 11 | Compact; no Issue Date key |
| `tabular_shifted` | 6 | Status not a lifecycle label; real status in `Sub Type` |
| `tabular_spaced_no_issue` | 2 | Spaced; no Issue Date key |

Canonical fields: `Status` (fallback `Sub Type` on shifted rows) → STATUS_NORMALIZED; `Issue Date` (fallback date-like `Status` on shifted rows) → PERMIT_DATE. No FILE_DATE or FINAL_DATE source.

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,140 / Active 691 / In Review 129 / Inactive 15 / missing 25.

Status map from DATA: Closed→Final; Issued/Approved→Active; Under Review / Online Application Received / Incomplete Application / Payment Needed / Address Assignment→In Review; Void / Deemed Incomplete→Inactive.

Main errors vs DATA:

- **Closed still Active (6):** `STATUS_ORIGINAL=issued` lagged live `Status=Closed` → FIXED to Final.
- **Issued still In Review (1):** `STATUS_ORIGINAL=under review` lagged → FIXED to Active.
- **Null statuses fillable (24):** Payment Needed (16), Address Assignment (1), Deemed Incomplete (1), plus 6 shifted rows whose lifecycle label sits in `Sub Type` (Closed×3, Approved×2, Under Review×1) → FILLED.
- **Unrecoverable (1):** `Status=SOLAR APP` with `Sub Type=Solar Residential` — not a lifecycle label; left missing.

### FILE_DATE

Missing on 2,000 / 2,000. DATA has no application / submittal / created date. `Issue Date` is issuance, not filing — not used as FILE_DATE. **0** fills/fixes.

### PERMIT_DATE

Missing on 406 / 2,000 before repair. When both present, existing PERMIT_DATE always matched parseable `Issue Date` (1,594 calendar-day matches; 0 mismatches).

Fillable after status repair:

- Issued→Active row with `Issue Date=08/14/2024` (1)
- Shifted Closed/Approved rows with date-like Status `06/08/2004` and `10/27/2011` (2)

→ **3 FILLED**. Remaining Active/Final gaps: Issue Date holds Work Description text (~387 rows overall; WD key absent) or is absent; one Issued row has implausible year 2420 (rejected).

### FINAL_DATE

Missing on 2,000 / 2,000. Closed maps to Final, but DATA has no completion / finaled / signoff timestamp. **0** fills/fixes.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_king_city.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_king_city_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 24 | 7 | 25 → 1 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 3 | 0 | 406 → 403 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Status transitions: `__NA__`→In Review 18; Active→Final 6; `__NA__`→Final 3; `__NA__`→Active 2; In Review→Active 1; `__NA__`→Inactive 1.

After repair, PERMIT_DATE coverage: Active 662/688 (96.2%); Final 922/1,149 (80.2%). FILE_DATE and FINAL_DATE remain 0% for all statuses — structural DATA limitation, not a mapping bug.
