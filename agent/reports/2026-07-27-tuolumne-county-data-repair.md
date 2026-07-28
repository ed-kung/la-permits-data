# Tuolumne County (CA) data repair

**Summary:** Tuolumne County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from two DATA schemas (GIS `permit_info` and SmartGov `main`/`extra`/`location`). Status is fully populated (**FILLED 3 · FIXED 60**): empty-status Issued rows filled Active; stale ISSUED/HOLD/OPEN rows with `PermitFinaledDate` upgraded to Final; civic EXPIRED/VOID/ACTIVE/HOLD/Incomplete strings overriding coarse `main.status` codes. `FILE_DATE` already nearly complete; **12 FIXED** to `dateSubmitted` when it fell after `dateCreated`. `PERMIT_DATE` missingness fell from **902 → 460** (**FILLED 442**), mainly from civic typed issue keys plus a few `PermitApprovedDate` fills. `FINAL_DATE` missingness fell from **1,340 → 1,031** (**FILLED 311 · FIXED 2**), filling from `PermitFinaledDate` / FINAL inspections / civic final keys, and clearing FINAL on two VIOLATION rows. Remaining gaps are mostly modern SmartGov form rows and legacy shells with no issuance or finaling timestamps.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Tuolumne County, CA** (n=2,002)
- Script: `agent/scripts/ca/data_repair_ca_tuolumne_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/processed_data/permits_ca_tuolumne_county_repaired.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

Two top-level payload families:

| Family | n | Description |
| --- | ---: | --- |
| `permit_info_*` | 1,191 | GIS / open-data scrape with `permit_info`, `inspections`, `search_data`, … |
| civic (`main`/`extra`/`location`) | 811 | CitizenServe / SmartGov portal; numeric `extra` field IDs by record type |

### permit_info variants

| Schema | n |
| --- | ---: |
| `permit_info_with_inspections` | 860 |
| `permit_info_dates_only` | 269 |
| `permit_info_applied_only` | 61 |
| `permit_info_empty` | 1 |

Canonical fields: `PermitStatus` → status; `PermitAppliedDate` → file; `PermitIssuedDate` (else Approved) → permit; `PermitFinaledDate` (else approved FINAL inspection) → final.

### civic variants

| Schema | n | Key date / status fields |
| --- | ---: | --- |
| `form_extra` | 313 | Modern Express/Standard building, EH, code compliance — no usable issue/final keys |
| `historic_building` | 312 | status `36354`; applied `36291`; approved `36294`; issued `36317`; finaled `36310` |
| `utility_encroachment` | 49 | status `37586`; applied `37527`; issued `37552`; final-ish `37530`/`37545` |
| `land_use` | 43 | status `34418`; applied `34377`; closed/approved dates `34421` |
| `encroachment_app` | 22 | status `37776`; applied `37720`; issued `37723`; final `37743`/`37736` |
| `empty_extra` | 21 | no extra fields |
| `tentative_map` | 19 | status `35744`; applied `35697`; final `35747` |
| `grading` | 16 | status `34187`; applied `34147`; issue `34150` (`34190` is a bulk 2023-09-18 migration stamp — ignored) |
| `misc_permit` | 16 | status `36936` (prefer over disposition `36934`); applied `36918` |

Canonical civic fields: prefer extra status string over `main.status` (−1/0/1/2); `dateSubmitted` else `dateCreated` → file; schema-specific issue/final keys → permit/final.

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,268 · Active 526 · In Review 121 · Inactive 84 · missing 3

Issues:
1. **3 null-status** `permit_info` rows with empty `PermitStatus` but Issued (+ Approved) dates → **FILLED Active**.
2. **~38 stale statuses** where `PermitFinaledDate` is populated but `PermitStatus` is still ISSUED / ACTIVE / HOLD / OPEN → **FIXED to Final** (same rule as Shasta County: finaled date overrides unless Inactive).
3. **~20 civic overrides** where granular extra status disagrees with `main.status=2` (complete):
   - EXPIRED / VOID → Inactive (16)
   - ACTIVE → Active (4)
   - HOLD / Incomplete → In Review (2)

When present, `permit_info.PermitStatus` maps cleanly:

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, COMPLETE, CLOSED | Final |
| ACTIVE, ISSUED, EXTENSION | Active |
| HOLD, IN PROGRESS, OPEN, INCOMPLETE | In Review |
| EXPIRED, VOID, VIOLATION | Inactive |

**After:** Final 1,286 · Active 520 · Inactive 100 · In Review 96 · missing 0  
Flags: **FILLED 3 · FIXED 60**

### FILE_DATE

**Before:** 2 missing (0.1%).

- `permit_info`: every populated `FILE_DATE` matches `PermitAppliedDate` (1,190/1,190). One VOID empty shell has no dates.
- civic: upstream used `dateCreated`; when `dateSubmitted` falls on a later calendar day (**12 rows**), prefer submitted (Lomita/Eureka convention). One Active `empty_extra` row has neither created nor submitted.

**After:** still 2 missing.  
Flags: **FILLED 0 · FIXED 12**

### PERMIT_DATE

**Before:** 902 missing (45.1%). Among Active/Final: high missingness driven almost entirely by civic rows (all 811 civic PERMIT_DATE null).

Root causes:
1. Upstream never extracted SmartGov typed issue keys (`36317`, `37552`, etc.).
2. A few Final `permit_info` rows have Approved but blank Issued (EH FINALED shells).

Repairs (Active / Final):
1. `permit_info`: Issued, else Approved → **FILLED 4**.
2. civic typed issue keys → **FILLED 438**.

**After:** 460 missing. Active/Final coverage: Active 435/520 (83.7%), Final 1,016/1,286 (79.0%).  
Flags: **FILLED 442 · FIXED 0**

Remaining Active/Final gaps are mostly `form_extra` (290), `empty_extra` (21), grading/misc shells, and ~15 legacy `permit_info` COMPLETE rows with neither Issued nor Approved.

### FINAL_DATE

**Before:** 1,340 missing (66.9%). Among Final: 50 `permit_info` + all 595 civic Final missing.

Issues:
1. Civic finals never populated from typed keys (`36310`, etc.).
2. ~20 Final `permit_info` rows missing `PermitFinaledDate` but with an approved FINAL inspection → fillable.
3. Two VIOLATION (Inactive) rows carried `PermitFinaledDate` / `FINAL_DATE` → cleared (not completion finals).
4. Non-Final rows that carried FINAL_DATE were mostly upgraded to Final via the finaled-date status rule, so FINAL_DATE is retained rather than cleared.

**After:** 1,031 missing. Final coverage: 971/1,286 (75.5%). Non-Final FINAL_DATE: 0.  
Flags: **FILLED 311 · FIXED 2**

Remaining Final gaps are mostly `form_extra` (229), grading (15, migration stamp rejected), misc_permit (11), and ~45 legacy `permit_info` COMPLETE/CLOSED shells with no finaled date or final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 3 | 60 | 3 | 0 |
| FILE_DATE | 0 | 12 | 2 | 2 |
| PERMIT_DATE | 442 | 0 | 902 | 460 |
| FINAL_DATE | 311 | 2 | 1,340 | 1,031 |

## Not repairable from DATA

- Modern SmartGov `form_extra` / code-compliance rows (Express/Standard building, EH annual, etc.) expose no issuance or finaling timestamps in `extra`.
- Historic Grading `34190` is a uniform 2023-09-18 bulk update, not a true final date.
- Legacy COMPLETE / CLOSED `permit_info` shells with empty Issued / Finaled and no usable FINAL inspection.
- One VOID `permit_info` shell and one civic Active shell with no dates at all.
