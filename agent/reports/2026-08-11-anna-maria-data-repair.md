# Anna Maria (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Anna Maria (2,000 records). DATA is a flat portal export with five key-layout variants and only one usable date field (`Issue Date` → issuance). STATUS_NORMALIZED had 87 nulls (mostly Lien Search field misalignment) and 12 stale values vs `DATA.Status`; repair filled 76 and fixed 12 (11 nulls remain on polluted parking/citation/commercial rows). FILE_DATE and FINAL_DATE are entirely absent from DATA and stay missing. PERMIT_DATE already matched every parseable `Issue Date` (1,471); the rest cannot be filled because `Issue Date` holds non-date text.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Anna Maria, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/fl/data_repair_fl_anna_maria.py`
- Artifact: `AGENT_DATA_PATH/anna_maria_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing keys |
| --- | ---: | --- |
| `flat_hash_wd` | 874 | `Permit#` + `Issue Date` + `Work Description` |
| `flat_space_wd` | 597 | `Permit #` + `Issue Date` + `Work Description` |
| `flat_space` | 229 | `Permit #` + `Issue Date` (no Work Description) |
| `flat_hash` | 211 | `Permit#` + `Issue Date` (no Work Description) |
| `flat_minimal` | 89 | no `Issue Date` (mostly Lien Search) |

Shared repair fields: `Status`, `Issue Date`, `Permit Type`. No application or finalization date exists in any schema.

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,162; Active 524; In Review 159; Inactive 68; **null 87**
- Canonical map from `DATA.Status`: Closed/Completed/Lien Search → Final; Issued/Approved → Active; Online Application Received/Paid/Pending/Under Review/Unpaid → In Review; Denied/Void/Withdrawn/Expired/Abandon/Rejected → Inactive.
- Nulls were not missing DATA — they were unmapped / polluted Status values:
  - Lien Search rows (76): Status is `"Lien Search"` or a street address (portal put address into Status) → **FILLED** Final via Status map or `Permit Type == "Lien Search"` fallback.
  - Remaining 11: Parking Violation Ticket (9), Beach Regulations (1), Commercial Building Permit with Work Description dumped into Status (1) — no reliable status token → left null.
- Incorrect non-null values (STATUS_ORIGINAL lagged current `DATA.Status`):
  - Active→Final (6) and In Review→Final (4) where DATA says Closed
  - In Review→Inactive (2) where DATA says Rejected or Withdrawn
- After: Final 1,248; Active 518; In Review 153; Inactive 70; **null 11**

### FILE_DATE

- Ideal: populated for all records.
- Before/after: **2,000 missing**. DATA has no application/submittal date. Dates occasionally appearing in `Work Description` Permit Notes are check/payment annotations, not used.
- Repair: 0 FILLED / 0 FIXED.

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Source: `Issue Date` when it is a real calendar date (1,471 rows). Every existing PERMIT_DATE matched that date (0 mismatches).
- 529 missing PERMIT_DATE rows have non-date `Issue Date` text (parking violation descriptions, work descriptions, "Lien search", pre-application labels) or no Issue Date — not fillable.
- After status repair: Active **517/518 (99.8%)** (1 Approved Special Event with no Issue Date); Final **921/1,248 (73.8%)**. Final gaps are mostly Parking Violation Tickets (220) and Lien Search (77) with non-date Issue Date.
- Repair: 0 FILLED / 0 FIXED.

### FINAL_DATE

- Ideal: populated for Final.
- Before/after: **2,000 missing**. Closed/Completed expose no finaled, CO, or completion timestamp.
- Repair: 0 FILLED / 0 FIXED. All Final rows remain without FINAL_DATE.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 76 | 12 | 87 → 11 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 0 | 0 | 529 → 529 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Ideal-field coverage after repair:

- FILE_DATE: 0% of all records (no source in DATA)
- PERMIT_DATE: 99.8% of Active; 73.8% of Final
- FINAL_DATE: 0% of Final (no source in DATA)

## Artifacts

- `agent/scripts/fl/data_repair_fl_anna_maria.py`
- `AGENT_DATA_PATH/anna_maria_repaired_sample.parquet`
