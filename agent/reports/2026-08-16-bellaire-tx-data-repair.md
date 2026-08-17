# Bellaire (TX) data repair

**Summary:** Bellaire was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,000 rows use a SmartGov portal payload (`Build Status` + `My Project` dates). STATUS_NORMALIZED was missing on 241 rows and wrong on 24 (mostly Expired* / Closed mislabels and Ready-for-Close-Out issued permits); FILE_DATE was nearly complete and matched Submitted; PERMIT_DATE matched Issued when present; FINAL_DATE was sparse because most Closed rows lack a Closed timestamp in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Bellaire, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_bellaire.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_bellaire_repaired.parquet`

## DATA schema

Every record has SmartGov top-level keys (`Department`, `My Project`, `Permit Type`, `Build Status`, `Permit Number`, `Permit Details`, contacts/fees/inspections). `Permit Details` and `Permit Inspections` are empty in this sample. Content variants in `INFERRED_SCHEMA`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| smartgov_minimal | 1,546 |
| smartgov_full | 334 |
| smartgov_no_desc | 114 |
| smartgov_empty | 6 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `Build Status` (+ Closed/Issued date overrides) | My Project date inference |
| FILE_DATE | `My Project.Submitted` | `My Project.Created` |
| PERMIT_DATE | `My Project.Issued` | `My Project.Approved` |
| FINAL_DATE | `My Project.Closed` | passed Building Final / COO inspection (none in sample) |

## Field assessment

### STATUS_NORMALIZED

Before repair: Final 1,611 / null 241 / Inactive 58 / Active 49 / In Review 41.

`Build Status` categories: Closed (1,619), null (136), Expired:* (116), Issued (49), Routed to Review (27), Application Submitted (19), Ready for Close Out (17), Pending Issuance… (14), Review Complete (2), Pending Letter (1).

Issues:
- **Null status (241):** upstream left many `Build Status` values unmapped (Routed to Review, Pending Issuance…, Expired:*, null Build Status). Repair FILLED 237 from Build Status + My Project dates.
- **Incorrect labels (24 FIXED):** Expired* kept as Active/In Review → Inactive; Closed kept as Active/In Review → Final; Ready for Close Out / null Build Status with Issued date → Active (issued override).
- **Not repairable:** 4 fully empty SmartGov shells (blank Build Status, Permit Number, Permit Type, and dates). Two additional empty shells already carried Active/Final from upstream and were left unchanged.

After repair: Final 1,640 / Active 138 / Inactive 116 / In Review 102 / null 4.

### FILE_DATE

Almost fully populated (9 missing). Where both present, FILE_DATE matched `Submitted` 1,989 / 1,989 at day resolution (0 mismatches). Prefer Submitted over Created.

Repair FILLED 5 missing from Submitted/Created. Remaining 4 missing are empty shells with no dates in DATA. One source quirk: Submitted (2013-01-14) after Issued (2012-12-28) on a Closed row — dates copied as-is from DATA.

After repair: FILE_DATE present for 100% of Active / Final / In Review / Inactive rows with usable payloads.

### PERMIT_DATE

Missing on 120 rows before repair. Where both present, PERMIT_DATE matched `Issued` 1,878 / 1,878. Approved alone is not used as issuance when Issued is blank for In Review rows.

Repair FILLED 10 for Active/Final/Inactive rows that had Issued (or Approved on Expired shells). In Review rows correctly keep PERMIT_DATE empty when not yet issued (spurious stamps cleared when Issued is blank).

After repair by status: Active 138/138 (100%); Final 1,637/1,640 (99.8%); Inactive 115/116 (99.1%); In Review 0/102 (0%). Three Final Closed rows have blank Issued and Approved in DATA.

### FINAL_DATE

Missing on 1,839 / 2,000 before repair. When present, FINAL_DATE matched `Closed` exactly (161 / 161). Only 170 rows have a parseable Closed date in My Project; historical Closed permits usually store `" - -"`.

Repair FILLED 9 Closed dates onto newly labeled Final rows. No inspection fallback available (`Permit Inspections` always empty). Non-Final rows do not retain FINAL_DATE after status resolution (20 null-status rows that already had Closed dates became Final and kept them).

After repair: Final 170/1,640 (10.4%); other statuses 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 237 | 24 | 241 → 4 |
| FILE_DATE | 5 | 0 | 9 → 4 |
| PERMIT_DATE | 10 | 0 | 120 → 110 |
| FINAL_DATE | 9 | 0 | 1,839 → 1,830 |

After repair, by status:

- **FILE_DATE:** 100% for all non-null statuses
- **PERMIT_DATE:** Active 100%; Final 99.8%; Inactive 99.1%; In Review 0%
- **FINAL_DATE:** Final 10.4%; non-Final remain empty

## Not repairable

- 4–6 empty SmartGov scrape shells with no status/date payload.
- 1,470 Final rows with blank `My Project.Closed` and no inspections → FINAL_DATE stays missing.
- 3 Final Closed rows with blank Issued/Approved → PERMIT_DATE stays missing.
- One Closed row where Submitted is after Issued in the source JSON (date-order anomaly left as reported by the portal).
