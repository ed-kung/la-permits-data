# Alameda (CA) data repair

**Summary:** First CA sample jurisdiction without an existing repair script was Alameda. Accela Citizen Access DATA is structurally consistent (`tasks_inspections` / `tasks_only`). STATUS had 32 gaps and 15 incorrect mappings (chiefly Application Complete→Final). FILE_DATE was fully populated but 43 rows used Accela import stamps instead of historical Application/APPLIED dates. PERMIT_DATE and FINAL_DATE were largely missing for Active/Final rows; the repair filled 755 permit dates and 954 final dates from workflow/inspection events.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in order. Alameda (CA) was the first without `agent/scripts/data_repair_{state}_{city}.py`.

Sample size: **2,000** rows.

## DATA schema

Almost all rows share the Accela scrape key set (`status`, `date`, `search_data`, `tasks`, `inspections`, …). `INFERRED_SCHEMA` records workflow richness:

| Schema | Count |
| --- | ---: |
| tasks_inspections | 1,207 |
| tasks_only | 792 |
| header_only | 1 |

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,381 · Inactive 283 · Active 221 · In Review 83 · missing 32.

Issues found:

1. **Incorrect Final mapping (14 rows):** `DATA.status == "Application Complete"` on Building - Pre Application records was mapped to Final. Workflow only shows intake (`Applied` / Application Complete); these are **In Review**.
2. **Incorrect Active mapping (1 row):** `Finaled` mapped to Active despite Application/FINALED events → **Final**.
3. **Unmapped statuses (14 rows filled):** fire-safety / entitlement values such as `OK to Inspect`, `Initial Inspection Passed`, `First Re-Inspection Passed`, `Fee Payment Required`, `10-day Public Notice`, `DUPLCATE`.
4. **Unrepairable (18 rows):** blank `DATA.status` and blank `search_data.Status` (workflow stuck at TBD / Fees Due only).

### FILE_DATE

Already populated for all 2,000 rows and matched `DATA.date` exactly. However, ~43 historical electrical / OTC shells have Accela **import** dates (often 2006–2008) while `Application` / `APPLIED` preserves the true historical filing date (e.g. 1935–1960s). Those were **FIXED**.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Before: 226 populated; all matched `Ready to Issue` / `Issued` (correct).
- Active/Final missing: 1,398.
- Repair fills from, in order: Ready to Issue/Issued → Application/Issued|ISSUED → Applied/Issued → (Approved status) earliest `*/Approved` task event.
- After: Active 189/230 (82.2%); Final 770/1,368 (56.3%).
- Remaining Final gaps are mostly FINALED/Finaled/Closed shells with no dated issuance event (only Application/FINALED or WIP tasks).

### FINAL_DATE

Ideal: populated for Final.

- Before: 118 populated, all on Final; matched Final* inspections or `Inspection`/`Finaled` (correct). No spurious finals on non-Final rows.
- Final missing: 1,263.
- Repair fills from: Inspection/Finaled|Final|Inspection Complete → Final* inspections (Approved/PASSED) → Certificate of Occupancy/Issued → Application/FINALED|FINAL.
- After: Final 1,072/1,368 (78.4%).
- Remaining gaps: Closed / Miscellaneous Revenue / project shells and finals with no completion signal.

## Repair performance

Script: `agent/scripts/data_repair_ca_alameda.py`  
Artifact: `AGENT_DATA_PATH/processed_data/permits_ca_alameda_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 14 | 15 | 32 → 18 |
| FILE_DATE | 0 | 43 | 0 → 0 |
| PERMIT_DATE | 755 | 0 | 1,774 → 1,019 |
| FINAL_DATE | 954 | 0 | 1,882 → 928 |

Status after repair: Final 1,368 · Inactive 284 · Active 230 · In Review 100 · missing 18.

## Not repaired

- 18 blank-status records with no usable `search_data.Status`.
- Active/Final rows whose workflow never records a dated Issued/Approved event.
- Final rows without final inspection, Inspection/Finaled, or Application/FINALED dates (common for Closed administrative / revenue records).

## Why so many PERMIT_DATE / FINAL_DATE values remain missing

The residual gaps look like a **data-model / migration problem**, not random scrape failures. After repair, ~640 Active/Final rows still lack PERMIT_DATE and ~296 Final rows still lack FINAL_DATE; in most of those cases DATA simply never stored a dated issuance or completion event.

### PERMIT_DATE

1. **Legacy Accela shells.** Final rows still missing PERMIT_DATE skew old (median file year **2004** vs **2014** when present; ~79% pre-2010). Many are electrical / plumbing / miscellaneous-revenue records whose workflow is only `Application` → `FINALED`/`APPLIED`, with **no Ready to Issue / Issued event**. Status says finaled, but issuance was never recorded as a dated task.
2. **TBD-only workflows.** Roughly 70% of remaining Active/Final PERMIT gaps have no dated task events at all—only `TBD` placeholders—so there is nothing in DATA to recover.
3. **Record types that aren’t classic building permits.** Closed projects, misc. revenue, design-review exemptions, special events, and fire-safety registrations often never go through a permit-issuance step, even when status is Final / Active / Approved.

### FINAL_DATE

1. **No inspection trail.** About 89% of Final rows still missing FINAL_DATE are `tasks_only` / zero inspections. Accela finaling is usually stamped via Final* inspections or `Inspection`/`Finaled`; without those, the date does not exist in DATA.
2. **Administrative “Closed/Finaled”.** A large share are Miscellaneous Revenue, Closed shells, special events, and exemptions—closed in the system without a field final / sign-off date. Of 116 Closed rows in this residual, 109 have no inspections.
3. **Same legacy pattern.** Older FINALED electrical OTC rows sometimes only have Application/FINALED (already used when dated); when even that is `TBD`, FINAL_DATE stays empty.

**Bottom line:** Alameda’s Accela history mixes modern permits (issuance + final inspection dates) with migrated/administrative records that only carry a coarse status. Remaining missing dates usually mean **the agency never stored those events in the workflow**, not that the repair mapping failed to find them.
