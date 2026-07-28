# Manteca (CA) data repair

**Summary:** Manteca was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from dual agency scrapes in `DATA` (legacy permit portal + Accela). Status is nearly complete (**FILLED 3 · FIXED 10**; 3 null remain with empty agency status). `FILE_DATE` missingness fell only slightly (**1,088 → 1,070**, **FILLED 18**) — portal Issued/Completed rows have no application date in `DATA`. `PERMIT_DATE` missingness fell sharply (**1,892 → 903**, **FILLED 989**), mainly by using portal `PaidValue` as an issuance proxy for Completed/Final rows. `FINAL_DATE` (**FILLED 8 · FIXED 4**) is complete for all portal Final rows; Accela `Completed` shells with empty task events remain unfilled. Chronology checks: 0 `FILE > PERMIT`, 0 `PERMIT > FINAL`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Manteca, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_manteca.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_manteca_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `permit_portal` | 1,110 | Legacy Logos/citizen portal: `Permit Summary`, `Payment Summary`, `Inspections`, … |
| `accela_shell` | 812 | Accela Civic Access; task shells present but no dated events (mostly `Completed` / expired) |
| `accela_tasks` | 76 | Accela with dated workflow events under `tasks` |
| `search_only` | 2 | Only `search_data` (TMP / incomplete records) |

Canonical fields:

| Field | Portal source | Accela source |
| --- | --- | --- |
| `STATUS_NORMALIZED` | `Permit Summary.StatusValue` | `DATA.status` |
| `FILE_DATE` | StatusValue Created / Pending date | `DATA.date` / `search_data['Date']` |
| `PERMIT_DATE` | StatusValue Issued date; else `PaidValue` | `Permit Issuance` / Issued events |
| `FINAL_DATE` | StatusValue Completed date | Inspection Completed / Finaled / CO Issued |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,652 · Inactive 168 · Active 103 · In Review 71 · missing 6

Issues:
1. **10 portal mismatches** vs `StatusValue`:
   - Permit Completed → Active (7) or In Review (1) → Fixed to Final
   - Permit Issued → In Review (2) → Fixed to Active
2. **3 Accela nulls** with mappable status: Fees Received / Pending Applicant → FILLED In Review
3. **3 remaining nulls** (unrepairable): empty `DATA.status` / empty search Status (1 Accela shell + 2 TMP `search_only`)

Portal StatusValue map:

| StatusValue pattern | `STATUS_NORMALIZED` |
| --- | --- |
| Permit Completed on … | Final |
| Permit Issued on … | Active |
| Pending Payment / Review as of … | In Review |
| Permit / Application Created … | In Review |

Accela `DATA.status` map:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Completed, Closed, Closed - Completed/Complete | Final |
| Issued | Active |
| Received, In Review, Revisions Approved, Ready to Issue, Fees Received, Pending Applicant | In Review |
| Permit Expired, Closed - Withdrawn, Closed - Denied | Inactive |

**After:** Final 1,660 · Inactive 168 · Active 98 · In Review 71 · missing 3  
Flags: **FILLED 3 · FIXED 10**

### FILE_DATE

**Before:** 1,088 missing (54.4%).

- Accela (888): already matched `DATA.date` / `search_data['Date']` for all rows — no changes.
- Portal (1,110): only 22 present before repair, all on Created rows where FILE matched StatusValue date.
- Portal Issued/Completed StatusValue dates are issuance/completion, **not** filing dates; `PaidValue` is a payment/issuance proxy, not used for FILE.
- Filled 18 Pending / Created StatusValue dates that were missing.

**After:** 1,070 missing (53.5%).  
Flags: **FILLED 18 · FIXED 0**

Coverage after: In Review 97%, Inactive 100%, Active 39%, Final 39% (portal Final almost never has an application date).

### PERMIT_DATE

**Before:** 1,892 missing (94.6%). Among Active/Final: 1,650 / 1,755 missing.

Root causes:
1. Portal Completed/Final rows had FINAL from StatusValue but no issuance field; upstream left PERMIT null.
2. Accela `Completed` shells (623 Final) have empty task events — no Issued marks.

Repairs (Active / Final only):
1. Portal Issued → StatusValue embedded date.
2. Portal Completed/Final → `Payment Summary.PaidValue` when it is a real date and ≤ FINAL (payment typically at issuance).
3. Accela → earliest `Permit Issuance` / Issued task event.

**After:** 903 missing (45.2%). Active 86.7% populated; Final 61.0%.  
Flags: **FILLED 989 · FIXED 0** (988 portal, 1 Accela)

Remaining gaps: Accela shells with no Issued events; ~16 portal Final with `PaidValue` = "Not paid" / empty.

### FINAL_DATE

**Before:** 969 missing (48.5%). Portal Final already matched StatusValue Completed date for 1,001 rows.

Issues / repairs:
1. **8 portal Completed** mislabeled Active (or missing FINAL) → FILLED from StatusValue date after status FIXED to Final.
2. **4 Accela Active** rows had Inspection Completed dates stored as FINAL while `DATA.status` remained Issued → cleared (**FIXED**), consistent with treating agency status as authoritative.
3. Accela Final with completion marks (`Inspection` Completed / Finaled, `CO Issued`) → FILLED when missing (tasks schema: 26 / 28 Final have FINAL).

**After:** 965 missing. Portal Final: **1,009 / 1,009** have FINAL. Accela shell Final: **0 / 623**.  
Flags: **FILLED 8 · FIXED 4**

## Performance summary

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 3 | 10 | 6 | 3 |
| FILE_DATE | 18 | 0 | 1,088 | 1,070 |
| PERMIT_DATE | 989 | 0 | 1,892 | 903 |
| FINAL_DATE | 8 | 4 | 969 | 965 |

Chronology after repair: **0** rows with FILE > PERMIT; **0** with PERMIT > FINAL.

## Not repairable from DATA

- Portal Issued/Completed **FILE_DATE** — no application/submittal field in the portal scrape.
- Accela **`accela_shell` Final** (623) — empty task events and empty inspections; no issuance or finaling date beyond fee invoice dates (aligned with FILE, not PERMIT/FINAL).
- 3 records with blank agency status (TMP / incomplete Accela).
