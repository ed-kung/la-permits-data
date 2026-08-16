# Anna (TX) data repair — STATUS_NORMALIZED and dates

**Summary:** Among TX sample jurisdictions ordered by name, Anna is the first without an existing repair script. Anna’s SmartGov `DATA` payloads map cleanly via `Build Status` and `My Project` dates (`Submitted`/`Created`/`Issued`/`Approved`/`Closed`). The main defects are 865 null `STATUS_NORMALIZED` values (null Build Status or unmapped `Expired:*`), 22 mislabeled statuses (mostly Expired stored as Active/In Review), 11 fillable missing `FILE_DATE`s, and missing `PERMIT_DATE`/`FINAL_DATE` where Issued/Approved/Closed exist. After repair, usable rows have full FILE coverage by status, Active/Final PERMIT at 99.8%, and Final FINAL_DATE at 99.3%; 70 empty SmartGov shells remain unrepaired.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` (193,630 rows). Walking `(JURISDICTION, STATE)` alphabetically, existing TX scripts cover Abilene, Allen, Austin, Dallas, Fort Worth, Houston, and San Antonio. **Anna** is the first gap → `agent/scripts/tx/data_repair_tx_anna.py`.

Sample size: **2,000** Anna records.

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `smartgov_full` | 961 | core + `ProjectDescription` (+ usually `Parcel Number`) |
| `smartgov_no_desc` | 693 | core + `Parcel Number`, no description |
| `smartgov_minimal` | 275 | SmartGov core without parcel/description |
| `smartgov_empty` | 71 | keyset present but no Build Status / identity / My Project dates |

Repair logic uses `Build Status` plus `My Project.Submitted|Created|Issued|Approved|Closed` (and passed Building Final / COO inspections as FINAL fallback) across all non-empty variants.

## Field assessment (before repair)

### STATUS_NORMALIZED

Upstream mapping from `STATUS_ORIGINAL` / `Build Status` covers Closed→Final, Issued/Approved→Active, Ready To Issue / Under Review / Pending→In Review, Cancelled→Inactive, and some Expired→Inactive — but leaves large gaps.

**Incorrectly missing (865):**

| Source signal | Approx. n | Expected |
| --- | ---: | --- |
| `Expired:*` with null status | 295 | Inactive |
| Null Build Status + Closed date | 161 | Final |
| Null Build Status + Issued (no Closed) | ~213 | Active |
| Null Build Status + Submitted/Created/Approved only | ~118 | In Review |
| Issued / Closed with null STATUS_ORIGINAL | ~8 | Active / Final |

**Incorrect non-null (27 FIXED after repair):**

| Before → after | n | Reason |
| --- | ---: | --- |
| Active → Inactive | 18 | `Expired:*` left as Active despite terminal expiry |
| In Review → Inactive | 4 | `Expired:*` left as In Review |
| In Review → Final | 3 | Closed / Finaled while STATUS_ORIGINAL lagged (`under review` / `ready to issue`) |
| In Review → Active | 2 | Issued while STATUS_ORIGINAL lagged (`under review` / `pending`) |

Root cause: upstream often maps only when `STATUS_ORIGINAL` is present and exact; null Build Status shells and `Expired: M/D/YYYY` strings were skipped or inconsistently classified.

### FILE_DATE

- Missing: **79 / 2,000**
- Present values already match `My Project.Submitted` at calendar-day resolution (1,918/1,918); Created is a common secondary stamp but Submitted is the application date
- Fillable from Submitted/Created: **11**
- Remaining **68** are empty shells with no date fields

### PERMIT_DATE

- Present values: **1,597** — all match `My Project.Issued` when Issued exists
- Missing: **403**
- Fillable: Issued present on missing rows (**20**); Approved present with blank Issued (**~172**, including many Closed finals)
- Ideal coverage gaps before repair: Active 10 missing, Final 23 missing

### FINAL_DATE

- Present values match `My Project.Closed` when both exist (**677**)
- Final rows missing FINAL: **3** (all `Finaled` with blank Closed)
- **161** FINAL_DATE values on null-status rows that already have Closed — correct once status is filled to Final; not spurious once status is repaired
- One Closed / In Review row and one Closed / null-status row lacked FINAL despite Closed → fillable

## Repair behavior

Canonical mappings:

- `Build Status` (+ Closed/Issued date overrides; Expired/Cancelled sticky Inactive) → `STATUS_NORMALIZED`
- Null Build Status → infer from Closed → Final, Issued → Active, else Submitted/Created/Approved → In Review
- `Submitted` (fallback `Created`) → `FILE_DATE`
- `Issued` (fallback `Approved`) → `PERMIT_DATE` for Active/Final/Inactive
- `Closed` (fallback passed Building Final / COO inspection) → `FINAL_DATE` only when effective status is Final; otherwise clear

Flags: `FILLED` for former missings; `FIXED` for corrected or cleared values. `INFERRED_SCHEMA` set per row.

## Performance (after repair)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 795 | 27 | 865 → 70 |
| FILE_DATE | 11 | 0 | 79 → 68 |
| PERMIT_DATE | 104 | 0 | 403 → 299 |
| FINAL_DATE | 2 | 0 | 1,322 → 1,320 |

Status distribution after: Final 685, Inactive 597, Active 503, In Review 145, null 70 (all `smartgov_empty`).

Date coverage after repair:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 503/503 (100%) | 503/503 (100%) | 0/503 |
| Final | 685/685 (100%) | 683/685 (99.7%) | 680/685 (99.3%) |
| In Review | 145/145 (100%) | 0/145 | 0/145 |
| Inactive | 597/597 (100%) | 513/597 (85.9%) | 0/597 |

Remaining gaps (not fillable from DATA):

- **70** empty SmartGov shells → status/dates stay missing (except one pre-labeled Final empty shell left as-is)
- **5** Final/`Finaled` rows with blank Closed and no passed Building Final/COO → FINAL_DATE stays missing
- **2** Active/Final without Issued/Approved (one Closed-only; one empty Final shell) → PERMIT_DATE stays missing
- **3** rows with FILE_DATE > PERMIT_DATE reflect agency Issued stamps predating a later Submitted (kept as in DATA)

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_anna.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_anna_repaired.parquet`
