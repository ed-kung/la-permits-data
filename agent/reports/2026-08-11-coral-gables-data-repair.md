# Coral Gables (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Coral Gables was first. Its DATA mixes Accela (`main`/`details`, 1,556 rows) and Tyler EnerGov (`entity`/…, 446 rows). STATUS_NORMALIZED was missing on 248 rows — mostly older Accela records with null `main.Status` but clear Final/Issued/Applied dates, plus 11 EnerGov `Approved/Pay Fees`. Repair filled 247 statuses and fixed 2 stale labels. FILE_DATE was already nearly complete (7 fills). PERMIT_DATE reached 100% of Active and 97.4% of Final. FINAL_DATE reached 100% of Final after 7 fills; 172 non-Final cancel/close stamps were cleared.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Coral Gables, FL** (2,002 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_coral_gables.py` (`data_repair`)

## DATA schema

| Payload | n | Canonical fields |
| --- | ---: | --- |
| Accela (`main`, `details`, `fees`, …) | 1,548 usable + 8 empty-`main` shells | `main.Status`, `Applied` / `Issued` / `Approved` / `Final` |
| EnerGov (`entity`, `details`, `contacts`, `fees`, `processing_status`) | 376 | `CaseStatus`, `ApplyDate`, `IssueDate`, `FinalDate` |
| EnerGov full (+ reviews/holds/attachments/more_info) | 70 | same |

`INFERRED_SCHEMA` prefixes: `accela`, `accela_shell`, `energov`, `energov_full`, with suffixes `_issued_finaled` / `_issued` / `_finaled` / `_applied` / `_status_only`.

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,306; Inactive 257; missing 248; Active 97; In Review 94.

**247 FILLED:**

| Source | → | n |
| --- | --- | ---: |
| Accela Status null, inferred from Final date | Final | 219 |
| EnerGov `Approved/Pay Fees` | In Review | 11 |
| Accela Status=`final`, SN null | Final | 6 |
| Accela Status null, Applied only | In Review | 6 |
| Accela Status null, Issued/Approved | Active | 4 |
| Accela Status=`pending`, SN null | In Review | 1 |

**2 FIXED:** Active→Inactive (`canceled`, stale `STATUS_ORIGINAL=issued`); In Review→Final (`final`, stale `STATUS_ORIGINAL=stop work`).

**Not repairable:** 1 Accela shell with empty `main` and no flat status.

After: Final 1,532; Inactive 258; In Review 111; Active 100; missing 1.

### FILE_DATE

Ideal: populated for all records.

- Already matched `Applied` / `ApplyDate` wherever both present.
- **7 FILLED** from Accela `main.Applied` (rows with Status set or dates present but FILE_DATE null).
- **1 remaining missing:** empty Accela shell with no ApplyDate in DATA.

Coverage after: 2,001 / 2,002 (99.95%).

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present, matched Accela `Issued` (else `Approved`) or EnerGov `IssueDate`.
- **22 FILLED** (5 Active, 7 Final, 10 Inactive) from Accela Issued/Approved.
- **5 FIXED** (cleared on EnerGov `Approved/Pay Fees` remapped to In Review that carried IssueDate).
- Remaining gap: **40 Final** with no IssueDate/Issued in DATA (33 EnerGov Finaled, 7 Accela finaled-only).

Coverage after: Active 100/100; Final 1,492/1,532 (97.4%); In Review 0/111; Inactive 52/258.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: all labeled Final already had FINAL_DATE; 171 Inactive (Accela canceled / EnerGov Cancelled) and 1 Active (EnerGov Issued) carried cancel/close FinalDate stamps.
- **7 FILLED** on Accela rows that became / were Final with `main.Final` present but FINAL_DATE null.
- **172 FIXED** (all clears of non-Final FINAL_DATE).
- After repair: Final 1,532/1,532 (100%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 247 | 2 | 248 → 1 |
| FILE_DATE | 7 | 0 | 8 → 1 |
| PERMIT_DATE | 22 | 5 | 375 → 358 |
| FINAL_DATE | 7 | 172 | 305 → 470 |

Post-repair consistency checks (status vs Accela/EnerGov maps; FILE vs Apply; PERMIT vs Issue/Approved and cleared on In Review; FINAL only on Final): **0 violations**.

Missing FINAL_DATE count rose because non-Final cancel stamps were correctly cleared.

## Artifacts

- Repair function: `agent/scripts/fl/data_repair_fl_coral_gables.py`
