# Palo Alto (CA) data repair

**Summary:** Palo Alto was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status missingness fell from **699 → 97** (**FILLED 602 · FIXED 12**): blank-Status older conversions inferred from workflow/inspection marks; unmapped portal statuses (`Approved Inspection Required`, `Meeting Scheduled`, etc.) filled; Approved/FIR|PLN|WGW and Not Required mislabeled In Review corrected. `FILE_DATE` already matched `DATA.date` for all 2,000 rows (**FILLED 0 · FIXED 0**). `PERMIT_DATE` gained **FILLED 5 · FIXED 6** (Fees Paid / early Ready-to-Issue dates corrected to Issued / Ready to Issue; a few Approved rows filled from RTI/Approval marks). `FINAL_DATE` gained **FILLED 930** from final-titled / Final Approval inspections (and rare Inspection-task Finaled marks), preferring finals on/after `PERMIT_DATE` to avoid pre-issuance optional finals. Final coverage is **933 / 939 (99.4%)**. Active PERMIT coverage is **627 / 653 (96.0%)**. No chronology inversions remain.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Palo Alto, CA** (n=2,000) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` (index 86 after Roseville)
- Script: `agent/scripts/ca/data_repair_ca_palo_alto.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_palo_alto_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Citizen Access scrapes with shared top-level keys: `status`, `date`, `tasks`, `search_data`, `inspections`, `more_details`, `record_type`, fees/contacts/conditions, etc. Sub-schemas reflect content richness:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,428 | Dated workflow events under `tasks` |
| `accela_shell` | 562 | Task shells present but no dated events (mostly older blank-Status conversions) |
| `accela_search_only` | 10 | No tasks; dates only in `search_data` / `DATA.date` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (= `search_data['Status']`); else workflow marks / final inspections |
| `FILE_DATE` | `DATA.date`; else `search_data['Date']`; else earliest Application Submittal event |
| `PERMIT_DATE` | `Permit Issuance` → Permit Issued / Issued; else `Ready To Issue` → Approved / Ready to Issue; else `Approval` → Approved* |
| `FINAL_DATE` | Inspection task Finaled / Final Approved / Complete; else latest final-titled or Final Approval inspection (on/after PERMIT_DATE when set) |

## Field assessment

### STATUS_NORMALIZED

**Before:** Active 606 · Final 509 · In Review 119 · Inactive 67 · missing 699

`DATA.status` → expected mapping (selected):

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled, Complete, Closed | Final |
| Permit Issued, Issued, Approved, Approved Inspection Required, FIR/PLN/WGW Approved, Approved With Conditions, Over the Counter Approved, Active, Decision Effective, GB - Appd Inspection Required | Active |
| Pending Resubmittal, In Plan Check, In Review, Under Review, Incomplete, Meeting Scheduled, Submitted, Ready to Issue, Open, FIR - Routed | In Review |
| Expired, Permit Expired, VOID/Void, BLD/FIR - Not Required | Inactive |

Issues:
1. **672 blank `DATA.status` / `search_data.Status`:** older Accela conversions with empty portal Status. Inferable from marks/inspections → **FILLED** Final (430), In Review (130), Active (37), Inactive (5). **97** remain missing (mostly `accela_shell` / `accela_search_only` with no dated events or final inspections).
2. **27 missing with non-blank status:** `Approved Inspection Required` (21), `Meeting Scheduled` (4), `Over the Counter Approved` (1), `Decision Effective` (1) → **FILLED**.
3. **12 mismatches vs `DATA.status` (FIXED):**
   - Approved With Conditions / FIR|PLN|WGW - Approved labeled In Review (10) → Active
   - BLD/FIR - Not Required labeled In Review (2) → Inactive

**After:** Final 939 · Active 653 · In Review 237 · Inactive 74 · missing 97  
Flags: **FILLED 602 · FIXED 12**

### FILE_DATE

**Before:** 0 missing (100%).

- `FILE_DATE` equals top-level `DATA.date` for all 2,000 rows (also consistent with `search_data['Date']` when present).
- No fill or fix needed.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**  
Coverage: **100%**.

### PERMIT_DATE

**Before:** 749 missing (37.5%). Among Active/Final: 24 / 1,115 missing (Active 23/606 · Final 1/509).

- When set, `PERMIT_DATE` usually matched `Permit Issuance` / Permit Issued (1,239 exact).
- **FIXED 6:** upstream used Fees Paid (or an earlier Ready-to-Issue fee date) instead of Issued / Ready to Issue — corrected to the issuance mark.
- **FILLED 5:** Active `Approved` rows with `Ready To Issue` / `Approval` marks but no Permit Issuance event; plus one blank-Status Final with an issuance mark.

Gaps after repair (744 overall; Active 26 · Final 353 still missing) are dominated by:
- **Newly inferred Final** blank-Status shells with final inspections but no issuance events (~350+).
- **Active `Permit Issued` shells** with empty Permit Issuance events (17).
- Departmental Approved statuses (`FIR`/`PLN` Approved, etc.) without dated issuance marks.

**After:** missing 744.  
Flags: **FILLED 5 · FIXED 6**  
Active coverage: **627 / 653 (96.0%)** · Final coverage: **586 / 939 (62.4%)**

### FINAL_DATE

**Before:** 1,997 missing (99.9%); only 3 Final rows had `FINAL_DATE`, each matching Inspection-task Finaled/Complete.

- Primary fill: inspections whose title contains “final” (or status is Final Approval / Approved - Final / Final Approved) — covers nearly all `Finaled` portal records and blank-Status conversions inferred as Final.
- Guardrail: when `PERMIT_DATE` is known, only accept finals on/after that date (avoids optional pre-issuance finals that produced PERMIT > FINAL inversions).

**After:** missing 1,067; Final coverage **933 / 939 (99.4%)**. Six Final rows still lack a usable post-permit final mark (including one `Closed` with no inspections).  
Flags: **FILLED 930 · FIXED 0**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 602 | 12 | 699 → 97 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 5 | 6 | 749 → 744 |
| `FINAL_DATE` | 930 | 0 | 1,997 → 1,067 |

Chronology after repair: **FILE > PERMIT: 0** · **PERMIT > FINAL: 0**.

## Not repairable from DATA

- 97 blank-Status shells with no dated events / final inspections → `STATUS_NORMALIZED` stays missing.
- Active `Permit Issued` shells with empty issuance events → `PERMIT_DATE` stays missing.
- Hundreds of inferred-Final conversions have final inspections but no issuance workflow → `PERMIT_DATE` stays missing despite Final status.
- A handful of Final/Closed records lack post-permit final inspections → `FINAL_DATE` stays missing.
