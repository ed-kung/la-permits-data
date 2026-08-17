# Bedford (TX) data repair

**Summary:** Bedford was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,000 rows share one CitizenServe payload (`main` / `extra` / `location`). STATUS_NORMALIZED already matches `main.status` 1:1; FILE_DATE was complete but lagged `dateSubmitted` on 104 rows (now FIXED); PERMIT_DATE and FINAL_DATE are universally missing with no reliable issuance or finaling timestamps in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Bedford, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_bedford.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_bedford_repaired.parquet`

## DATA schema

Every record has top-level keys `main`, `extra`, `location`. `main.status` codes map to portal lifecycle (`0=draft`, `1=active`, `2=complete`, `-1=stopped`). Content variants recorded in `INFERRED_SCHEMA`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| citizenserve_building | 984 |
| citizenserve_code | 550 |
| citizenserve_draft | 312 |
| citizenserve_registration | 138 |
| citizenserve_planning | 15 |
| citizenserve_other | 1 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `main.status` | — |
| FILE_DATE | `main.dateSubmitted` | `main.dateCreated` |
| PERMIT_DATE | — (none reliable) | — |
| FINAL_DATE | — (none reliable) | — |

## Field assessment

### STATUS_NORMALIZED

| main.status | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| 2 | complete | Final | 1,063 |
| 1 | active | Active | 580 |
| 0 | draft | In Review | 312 |
| -1 | stopped | Inactive | 45 |

No missing values; 0 mismatches vs `main.status`. A small code-enforcement subset carries `extra['Case Status']` that disagrees with the portal code (4 Closed while Active; 4 Active while Final). Repair keeps `main.status` as authoritative so STATUS stays aligned with STATUS_ORIGINAL.

### FILE_DATE

Fully populated (0 missing). On 1,896 rows the value already matched the preferred source (`dateSubmitted` when present, else `dateCreated`) at UTC day resolution. On 104 rows FILE_DATE matched `dateCreated` while `dateSubmitted` fell on a later calendar day (application drafted then submitted later) — those were FIXED to the submittal date.

### PERMIT_DATE

Universally missing (2,000 / 2,000). DATA has no issuance or approval timestamp. Numeric ASI fields that look date-like (e.g. `16634`, `17114`, `17117`) sit next to contractor-name ASI fields and include non-dates such as `40209` — consistent with insurance/license expiration, not permit issuance. `lastUpdatedDate` and `expirationDate` are not used as approval proxies.

### FINAL_DATE

Universally missing (2,000 / 2,000). No finaled / completion / signoff field in `main` or `extra`. Named date fields (garage-sale / event start–end, anticipated work dates, CE abatement ASI dates) are schedule or operational stamps, not permit finaling dates.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 104 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/580 (0%), Final 0/1,063 (0%)
- **FINAL_DATE:** Final 0/1,063 (0%); non-Final remain empty

## Not repairable

- All Active/Final rows lack issuance timestamps in DATA → PERMIT_DATE stays missing.
- All Final rows lack finaling/completion timestamps in DATA → FINAL_DATE stays missing.
- 8 code cases where `Case Status` disagrees with `main.status` left unchanged (portal status treated as source of truth).
