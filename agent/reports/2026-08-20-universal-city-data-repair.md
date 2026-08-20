# Universal City (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Universal City was first. Its DATA is a SmartGov portal payload (`smartgov_full` / `smartgov_no_desc` / `smartgov_no_parcel` / `smartgov_empty`). Status was often null or mis-mapped (especially Expired* and Closed). Dates already match `My Project` when present; most gaps are fillable. After repair, usable Active/Final rows have full FILE/PERMIT coverage and all Final rows have FINAL_DATE. Fifteen empty SmartGov shells remain unrepaired.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in appearance order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Universal City, TX** (2,000 sample rows). Remaining missing at selection time: Windcrest, West Lake Hills, Shavano Park, Uhland, Sunset Valley.

## DATA schema

SmartGov community portal JSON (same family as Portland / La Marque / Bellaire):

| Schema | n | Distinguishing keys |
| --- | ---: | --- |
| `smartgov_full` | 1,383 | `ProjectDescription` + `Parcel Number` + core |
| `smartgov_no_desc` | 600 | `Parcel Number` + core, no description |
| `smartgov_no_parcel` | 2 | core without parcel / description |
| `smartgov_empty` | 15 | SmartGov keyset, blank `My Project` / status |

Relevant fields:

| DATA field | Role |
| --- | --- |
| `Build Status` | Raw status (`Closed`, `Issued`, `Expired: …`, etc.) |
| `My Project.Submitted` (else `Created`) | Application / file date → `FILE_DATE` |
| `My Project.Issued` (else `Approved`) | Issuance / approval → `PERMIT_DATE` |
| `My Project.Closed` | Completion / sign-off → `FINAL_DATE` |
| `Permit Inspections` | Present but empty in sample; inspection fallback unused |

## Field assessment

### STATUS_NORMALIZED

Before repair: 887 null, 828 Final, 224 Active, 38 In Review, 23 Inactive.

| Issue | n | Cause |
| --- | ---: | --- |
| Null status, Expired* Build Status | ~209 | Expired never mapped → fill Inactive |
| Null status, null Build Status + dates | ~594 | Infer from Closed / Issued / Submitted |
| Null status, Closed / Issued / Approved-Pending | ~84 | Build Status present but never mapped |
| Closed labeled Active | 34 | Should be Final |
| Expired* labeled Active / In Review | 25 | Sticky Inactive |
| Issued / Required-Inspections labeled In Review | 3 | Issued date → Active |
| Closed labeled In Review | 1 | → Final |

Empty shells (15) keep null status; not repairable from DATA.

### FILE_DATE

- Missing before: **81 / 2,000**
- When present, equals calendar day of `Submitted` on every row
- **70** fillable from `Submitted` / `Created`; **11** empty shells remain missing
- No incorrect values to fix

### PERMIT_DATE

- Missing before: **247 / 2,000**
- When present, equals `Issued` on every comparable row
- After status repair, Active/Final gaps fill from `Issued` else `Approved`
- Ideal coverage (Active + Final populated) met on all usable rows

### FINAL_DATE

- Missing before: **1,025 / 2,000** (includes many non-Final / null-status rows)
- Equals `Closed` on 974 / 975 comparable Final rows; **1** mismatch (`2024-03-26` vs Closed `8/22/2024`) → FIXED
- Final gaps fillable from `Closed` after status repair (including Closed→Active mis-maps)
- `Permit Inspections` empty in sample → no inspection fallback

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_universal_city.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA`; overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED`
- Status map includes Universal City’s `Approved, Pending Payment or License Information`, `Voided`, and `Required Inspections Complete - In Final Review`
- Sticky Inactive for Expired* / Voided; Closed-date / Issued-date overrides as in Portland
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_universal_city_repaired.parquet`

## Repair performance (TX sample, n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 876 | 63 | 887 | 11 |
| FILE_DATE | 70 | 0 | 81 | 11 |
| PERMIT_DATE | 88 | 0 | 247 | 159 |
| FINAL_DATE | 88 | 1 | 1,025 | 937 |

After-repair status: Final 1,063 · Active 529 · Inactive 257 · In Review 140 · null 11.

Coverage on usable schemas (`smartgov_empty` excluded):

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 100% | 0% (expected) |
| Final | 100% | 100% | 100% |
| In Review | 100% | 0% (expected) | 0% (expected) |
| Inactive | 100% | 96.5% | 0% (expected) |

Remaining gaps: 11 empty shells (null status / dates); 9 Inactive rows with no Issued/Approved; 1 chronology oddity where PERMIT_DATE > FINAL_DATE after aligning to agency Closed. No FILE_DATE > PERMIT_DATE violations.
