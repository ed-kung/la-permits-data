# Plantation (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Plantation was first. Its DATA is an Accela Citizen Access payload (`status`, `date`, `search_data`, `tasks`, usually `inspections`). STATUS_NORMALIZED had 10 missing (Pickup/Sent) and 8 wrong Complied→In Review labels. FILE_DATE was already complete and correct. PERMIT_DATE already matched Issued workflow events whenever present; remaining Active/Final gaps are mostly History Permits with no issuance events. FINAL_DATE was the main gap: 66 fills from Close Closed/Complete, 2 fixes to the latest Inspections Complete, and 2 clears of Cancelled rows that still carried a closeout stamp — leaving FINAL_DATE on 90.7% of Final rows.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Plantation, FL** (1,998 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_plantation.py` (`data_repair`)

## DATA schema

All records are Accela-shaped. Variants (INFERRED_SCHEMA prefixes):

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `accela_full` | 1,789 | dated task events + `inspections` list |
| `accela_shell` | 203 | portal payload but no dated task events |
| `accela_basic` | 6 | dated task events, no `inspections` list |

Content suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) reflect which of file / issued / final dates are derivable from DATA.

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status` (fallback `search_data.Status`) |
| FILE_DATE | `DATA.date` / `search_data.Date` |
| PERMIT_DATE | earliest `Issued` on Permit Issuance Review / Registration Issuance / Issue Permit |
| FINAL_DATE | latest Inspections `Complete`; else Close `Closed`/`Complete`; else Certificate Review `Approved`; else Approved final-ish inspection |

## Field assessments

### STATUS_NORMALIZED

10 missing; rest already matched `DATA.status` for the common Closed/Issued/Cancelled/etc. values.

**10 FILLED** (unmapped upstream):

| After | `DATA.status` | n |
| --- | --- | ---: |
| In Review | Pickup | 6 |
| In Review | Sent | 4 |

**8 FIXED:**

| Before → After | `DATA.status` | n |
| --- | --- | ---: |
| In Review → Final | Complied | 8 |

Cause: Pickup/Sent were never mapped; Complied (code/building enforcement resolved) was treated as still in review. After repair: Final 1,553; Inactive 225; In Review 151; Active 69; missing 0.

### FILE_DATE

Ideal: populated for all records. **Already correct** — 0 missing; every FILE_DATE matches `DATA.date` at day resolution. No FILLED/FIXED.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present, equaled the earliest Issued workflow event (including Registration Issuance).
- **0 FILLED / 0 FIXED** — no Active/Final row had an Issued event that was missing from PERMIT_DATE.
- Remaining gap: **135 Active/Final** still missing PERMIT_DATE (mostly History Permits / shells with empty task events; also a few Delinquent/Complete/Active rows with no Issued stamp). Not inventable from DATA.

Coverage after repair: Active 57/69 (82.6%); Final 1,422/1,553 (91.6%); In Review 0/151; Inactive 81/225.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 202 Final rows missing FINAL_DATE; 2 Inactive (Cancelled) rows had FINAL_DATE from an Inspections Complete that preceded a later Close Cancelled.
- Almost all existing Final FINAL_DATE values already equal Inspections `Complete` (latest when a single Complete exists). Two rows used an earlier Complete while a later Complete existed.
- **66 FILLED** from Close `Closed`/`Complete` when Inspections Complete was absent.
- **4 FIXED:** 2 updated to latest Inspections Complete; 2 cleared on Cancelled Inactive rows.
- Remaining: **144 Final** rows with neither Inspections Complete, Close Closed/Complete, certificate approval, nor a usable final inspection date (empty task shells / Close still TBD).

Coverage after repair: Final 1,409/1,553 (90.7%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 10 | 8 | 10 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 438 → 438 |
| FINAL_DATE | 66 | 4 | 653 → 589 |

Post-repair consistency checks (status vs `DATA.status` map; FILE vs `DATA.date`; PERMIT vs Issued event when present; FINAL only on Final and equal to derived closeout): **0 violations**.

## Artifacts

- Repair function: `agent/scripts/fl/data_repair_fl_plantation.py`
- Repaired sample parquet: `AGENT_DATA_PATH/plantation_repaired_sample.parquet`
