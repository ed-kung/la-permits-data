# Hayward (CA) data repair

**Summary:** Hayward was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Tyler EnerGov `DATA` JSON. Status is now fully populated (**FILLED 3**): unmapped `Reviewed and Approved` and `Non-Exempt` rows → In Review. `FILE_DATE` already matched `entity.ApplyDate` for all 2,000 rows (no changes). `PERMIT_DATE` already matched `IssueDate` whenever present; 2 Final rows lack `IssueDate` and remain missing. Spurious `FINAL_DATE` on 440 non-Final rows (Issued / Expired / Cancelled / On Hold / Exempt / etc.) was cleared (**FIXED 440**). Final coverage of `FINAL_DATE` stays at **1,247 / 1,252** (5 Complete rows have no FinalDate in DATA).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Hayward, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_hayward.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Tyler EnerGov payloads with top-level keys `entity`, `details`, `fees`, `contacts`, `processing_status`. Sub-schemas:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,960 | Standard EnerGov payload |
| `entity_fees_reviews` | 40 | Plus empty `reviews` / `holds` / `attachments` / `more_info` keys |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (fallback: `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` (fallback: `details.ApplyDate`) |
| `PERMIT_DATE` | `entity.IssueDate` (fallback: `details.IssueDate`) |
| `FINAL_DATE` | `entity.FinalDate` (fallback: `details.FinalizeDate`) |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,252 · Inactive 500 · Active 149 · In Review 96 · missing 3

Issues:
1. **3 null `STATUS_NORMALIZED`** for CaseStatus values upstream never mapped:
   - Reviewed and Approved (2) — plans approved, not yet issued (`Issued=False`, null IssueDate) → In Review
   - Non-Exempt (1) — soft-story classification (peer of Exempt → In Review) → In Review

All other CaseStatus values already mapped correctly:

| `CaseStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| Complete | Final |
| Issued | Active |
| Expired, Cancelled, Denied | Inactive |
| In Review, Fees Due, Fees Paid, Submitted, Submitted - Online, Completeness Check, In-Complete, On Hold, Exempt | In Review |

Note: `Completeness Check` in DATA has a trailing space; lookup strips whitespace.

**After:** Final 1,252 · Inactive 500 · Active 149 · In Review 99 · missing 0  
Flags: **FILLED 3 · FIXED 0**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `entity.ApplyDate` at UTC calendar-day resolution.
- `details.ApplyDate` differs by one calendar day on 15 rows (timezone day-boundary); entity is authoritative and already matches `FILE_DATE`.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 165 missing (8.3%). Among Active/Final: 2 / 1,401 missing.

- Whenever `entity.IssueDate` is present, `PERMIT_DATE` already matches it (1,835 / 1,835).
- Two Final (`Complete`) rows have null IssueDate and `Issued=False` (Fire - Operational; Legacy archive) → cannot fill from DATA.

**After:** still 165 missing. Active 100% · Final 99.8%.  
Flags: **FILLED 0 · FIXED 0**

### FINAL_DATE

**Before:** 313 missing (15.7%). Among Final: 5 / 1,252 missing. **440 non-Final rows incorrectly carried FINAL_DATE** from `entity.FinalDate`:

| Status | Spurious FINAL_DATE |
| --- | ---: |
| Active (Issued) | 77 |
| Inactive (Expired 342, Cancelled 13) | 355 |
| In Review (On Hold / Exempt / In Review) | 7 |
| null (Non-Exempt) | 1 |

On Issued rows, FinalDate often equals ApplyDate/IssueDate (legacy stamp), not a Complete sign-off. On Expired/Cancelled it is a close/expire-adjacent stamp. `ExpireDate` is a validity window, not a completion date.

Repairs:
1. Keep / set FINAL_DATE from FinalDate/FinalizeDate only when effective status is Final.
2. Clear FINAL_DATE when effective status is not Final (**FIXED** to null).

Five Complete rows still lack FinalDate/FinalizeDate and have no usable finaling inspection → stay missing.

**After:** 753 missing (37.7%). Final 99.6% populated · Active/In Review/Inactive 0%.  
Flags: **FILLED 0 · FIXED 440**

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 3 | 0 | 3 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 165 | 165 |
| FINAL_DATE | 0 | 440 | 313 | 753 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_hayward.py`
- Repaired sample: `AGENT_DATA_PATH/hayward_repaired_sample.parquet`
