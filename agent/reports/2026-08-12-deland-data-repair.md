# DeLand (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, DeLand was first. Its DATA is an Accela Citizen Access payload (`status` / `date` / `tasks` / `search_data` / `inspections`). Upstream left **33** STATUS_NORMALIZED null (mainly `Issued Missing NOC`) and often copied Permit Issuance **Ready to Issue** into PERMIT_DATE instead of **Issued**. FINAL_DATE usually matched Inspection `Complete` / `Final Inspection Complete`, often one day before Close / C of O. After repair: status complete (FILLED 33 · FIXED 3); PERMIT_DATE aligned to Issued (FILLED 3 · FIXED 815); FINAL_DATE filled/fixed from Close / final-inspection / precheck / CE / lien / declarations marks (FILLED 132 · FIXED 424). Final coverage 1,389/1,390; Active PERMIT_DATE 226/232. Zero FILE→PERMIT or PERMIT→FINAL inversions.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **DeLand, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_deland.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_deland_repaired.parquet`

## DATA schema

| Family | n (approx) | Notes |
| --- | ---: | --- |
| `accela_permit_*` | ~1,759 | Permit Issuance + Close / Inspection workflow |
| `accela_code_enforcement_*` | 59 | Case Intake / investigation tasks |
| `accela_lien_history_*` | 48 | Utility / code lien + permit history |
| `accela_declarations_*` | 33 | Business tax declarations review |
| `accela_precheck_*` | 20 | Building pre-check (no Permit Issuance) |
| `accela_shell_*` / `accela_other_*` | ~81 | Sparse BTR / templates / other |

Suffixes `_issued_finaled`, `_issued`, `_finaled`, `_applied` mark which canonical dates are recoverable.

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status` (else `search_data.Status`) |
| FILE_DATE | `search_data.Date` else `DATA.date` else Application Submittal Accepted |
| PERMIT_DATE | Earliest Permit Issuance `Issued` / `Permit Issued` / `Issued Missing NOC` |
| FINAL_DATE | Latest of Close Closed / C of O / C of C; Closed.Completed; Inspection Final Inspection Complete; Pre-Check Complete; Declarations Completed; CE Violation Corrected; passed final-ish inspections; else Inspection Complete |

## Field assessments

### STATUS_NORMALIZED

**33 missing** before repair — unmapped `Issued Missing NOC` (24), `Additional Info Needed` (4), `Home Business` (3), `Declarations Due` (2).

Among populated rows, STATUS_NORMALIZED tracked `STATUS_ORIGINAL` and was correct for the common Closed / Issued / CofO / Void set. Three rows had stale `STATUS_ORIGINAL=in review` while live `DATA.status=Issued` → incorrectly labeled In Review.

**33 FILLED / 3 FIXED.** After: Final 1,390; In Review 306; Active 232; Inactive 72; **0 null**.

### FILE_DATE

Ideal: populated for all records.

- FILE_DATE equals `DATA.date` for all 2,000 rows (and `search_data.Date` when present).
- **0 FILLED / 0 FIXED.** Coverage after repair: 100% for every status.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Upstream often used Permit Issuance **Ready to Issue** (815 rows where that stamp preceded a later Issued date; 768 of those had PERMIT_DATE equal to Ready while Issued differed).
- **815 FIXED** (Ready → Issued, plus clears of unsupported Ready stamps on In Review with no Issued event).
- **3 FILLED** where Issued existed but PERMIT_DATE was blank (status remapped to Active).
- Missing count rose 442 → 486 because Ready-only In Review stamps were cleared (correct: not issued).
- Remaining Active gap: **6** Business Tax Receipt / Inspection Template shells with no Permit Issuance task.
- Remaining Final gap: **129** — mostly lien history, code enforcement Case Closed, declarations Completed, and a few Closed shells with no Issued event in DATA.

Coverage after repair: Active 226/232 (97.4%); Final 1,261/1,390 (90.7%); In Review 4/306 (prior Issued under revision); Inactive 23/72 (issued-then-voided/expired). **1,514/1,514** PERMIT_DATE equals Issued event when both present. **0** FILE_DATE > PERMIT_DATE inversions.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream preferred Inspection `Complete` / `Final Inspection Complete`, often one day (or more) before Close Closed / C of O.
- Repair takes the later of Close / certificate / final-inspection / precheck / CE / declarations / lien closure marks.
- **132 FILLED** / **424 FIXED** (value corrections plus clears of 6 spurious FINAL_DATE on Active/Inactive).
- Remaining Final gap: **1** — `BD19-1542` Closed Building Renovation stuck in Additional Info / Resubmittal with no Close or Inspection final mark in DATA.

Coverage after repair: Final 1,389/1,390 (99.9%); Active / In Review / Inactive 0%. **0** PERMIT_DATE > FINAL_DATE inversions.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 33 | 3 | 33 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 3 | 815 | 442 → 486 |
| FINAL_DATE | 132 | 424 | 737 → 611 |

PERMIT_DATE / FINAL_DATE missing counts after repair are dominated by non-building shells (CE, liens, declarations, BTR) that never had issuance / final stamps, plus intentional clears of Ready-to-Issue and non-Final FINAL_DATE values.
