# Mission Viejo (CA) data repair

**Summary:** Mission Viejo was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Tyler EnerGov `DATA` JSON (`entity` / `details`). Status: **FIXED 1,035** (1,029 stale `Issued`+FinalDate shells Active→Final; 6 review/fees/stop-work shells with IssueDate → Active). `FILE_DATE` already matched `ApplyDate` for all 2,000 rows. `PERMIT_DATE`: **FIXED 54** (cleared EnerGov `1900-01-01` sentinels). `FINAL_DATE`: **FIXED 786** (cleared sentinels and non-Final closure stamps). After repair, Active/Final have 100% `PERMIT_DATE` coverage; Final has 99.9% `FINAL_DATE` (1 agency-`Final` row lacks a credible FinalDate).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Mission Viejo, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_mission_viejo.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_mission_viejo_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `entity`, `details`, `contacts`, `fees`, `processing_status`. Two also carry a reviews bundle:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,998 | Core EnerGov payload |
| `entity_fees_reviews` | 2 | Plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` / `details.PermitStatus`, with date upgrades from IssueDate / FinalDate / FinalizeDate |
| `FILE_DATE` | `entity.ApplyDate` (details fallback) |
| `PERMIT_DATE` | `entity.IssueDate` (details fallback) |
| `FINAL_DATE` | `entity.FinalDate`; else `details.FinalizeDate` |

`CaseStatus` and `details.PermitStatus` agree on every sample row. `CaseType` is mostly `Legacy Permit - Legacy Permit` (1,979), plus Parking (13) and Transportation (8). EnerGov uses `1900-01-01` as a null placeholder for IssueDate / FinalDate / FinalizeDate.

## Field assessment

### STATUS_NORMALIZED

**Before:** Active 1,756 · Inactive 131 · In Review 64 · Final 49 · missing 0

Upstream mapping from `STATUS_ORIGINAL` / CaseStatus was consistent with the raw labels (`issued`→Active, `complete`/`final`→Final, `expired`/`void`/`cancelled`→Inactive, review/fees/submitted→In Review). Repairable problems came from **date evidence that the label ignored**:

1. **Issued + credible FinalDate still labeled Active (1,029).** `entity.FinalDate` / `details.FinalizeDate` were real completion stamps (always ≥ IssueDate) but CaseStatus remained `Issued` → **FIXED** to Final.
2. **Review-pipeline labels with IssueDate (6) → Active:** CaseStatus `In Review` (3), `Fees Due` (2), `Stop Work Order` (1).

| Change | n | Reason |
| --- | ---: | --- |
| Active → Final | 1,029 | CaseStatus Issued + credible FinalDate |
| In Review → Active | 6 | IssueDate present (In Review / Fees Due / Stop Work Order) |

Inactive terminal labels (`Expired`, `Void`, `Cancelled`) are sticky even when FinalDate is present as a closure stamp (1 Expired row had a real FinalDate; status stays Inactive).

**After:** Final 1,078 · Active 733 · Inactive 131 · In Review 58 · missing 0  
Flags: **FILLED 0 · FIXED 1,035**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` already equals `entity.ApplyDate` at day resolution.
- No fills or fixes needed.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 8 null + 54 sentinel `1900-01-01` = 62 effectively missing (3.1%).

Root causes:
1. **54 sentinel IssueDate values** copied into `PERMIT_DATE` (mostly In Review / never-issued shells) → **FIXED** (cleared to null).
2. 8 true nulls remain where IssueDate is absent (Inactive void/expired and In Review intake) — not repairable from DATA.
3. Wherever a credible IssueDate was present, `PERMIT_DATE` already matched (0 day mismatches vs source).

**After:** 62 missing (all non-Active/Final, or Inactive without IssueDate). Active/Final coverage **100%**.  
Flags: **FILLED 0 · FIXED 54**

Five source rows have ApplyDate after IssueDate (mostly Transportation permits); chronology is left as in DATA.

### FINAL_DATE

**Before:** 137 null + 785 sentinel `1900-01-01` = 922 effectively missing; 1,078 rows had a real final stamp (including 1,029 Active and 1 Inactive).

Root causes:
1. **Sentinel `1900-01-01` treated as a real final date (785 rows)** across Active / In Review / Inactive / Final → cleared when non-Final or when Final lacks a credible stamp (**FIXED**).
2. **1,029 Active rows already carried a real FinalDate** but status was wrong → status FIXED to Final; `FINAL_DATE` already matched source (no date flag).
3. **Spurious real FinalDate on 1 Expired row** → cleared (Inactive sticky).
4. **1 CaseStatus `Final` row** has only sentinel FinalDate → stays Final with null `FINAL_DATE` (agency label authoritative; not repairable).

**After:** 923 missing; every non-Final row has null `FINAL_DATE`; Final coverage **1,077 / 1,078 (99.9%)**.  
Flags: **FILLED 0 · FIXED 786**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1,035 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 54 | 8 → 62 (cleared 54 sentinels) |
| FINAL_DATE | 0 | 786 | 137 → 923 (cleared sentinels / non-Final stamps) |

Ideal-coverage checks after repair:

| Check | Result |
| --- | --- |
| FILE_DATE populated | 2,000 / 2,000 (100%) |
| Active/Final have PERMIT_DATE | 1,811 / 1,811 (100%) |
| Final have FINAL_DATE | 1,077 / 1,078 (99.9%) |
| Non-Final FINAL_DATE null | 922 / 922 (100%) |
| PERMIT &lt; FILE (source DATA) | 5 |
| FINAL &lt; PERMIT | 0 |

## Not repaired

- `ExpireDate` is a permit validity window, never used as FILE / PERMIT / FINAL.
- Inactive void/expired shells with null IssueDate keep missing `PERMIT_DATE`.
- One `Final` CaseStatus row with only sentinel FinalDate keeps null `FINAL_DATE`.
- Five ApplyDate &gt; IssueDate inversions are present in the agency JSON (left unchanged).
