# Arvin (CA) data repair

**Summary:** Arvin was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the OpenGov / SmartGov `DATA` JSON. Status was remapped from live numeric `main.status` (**FIXED 36**): stale `STATUS_ORIGINAL` labels had left 34 `complete` (status=2) rows as Active, one as In Review, and one `stopped` row as Active. `FILE_DATE` was corrected from `dateCreated` to `dateSubmitted` where the submittal fell on a later calendar day (**FIXED 53**); coverage remains 100%. `PERMIT_DATE` and `FINAL_DATE` are universally missing and cannot be recovered — the payload has no issuance or finaling timestamps.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Arvin, CA** (n=1,766)
- Script: `agent/scripts/ca/data_repair_ca_arvin.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `main`, `extra`, and `location`. Sub-schemas reflect `extra` form content:

| Schema | n | Description |
| --- | ---: | --- |
| `building_form` | 1,657 | Building permit fields (Description of Work, Type of Construction, …); often also carries numeric OpenGov IDs |
| `planning_form` | 34 | Master Planning / site-development fields (Zoning District, Site Plan Fee, …) |
| `encroachment_form` | 34 | Encroachment / grading fields (Requested Start Date:, Current Permit Status, …) |
| `other_form` | 19 | Misc. named forms without the signatures above |
| `numeric_legacy` | 11 | Numeric OpenGov field IDs without named form signatures |
| `code_enforcement_form` | 11 | Code-enforcement workflow fields |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `main.status` (−1/0/1/2) |
| `FILE_DATE` | `main.dateSubmitted` (fallback: `dateCreated`) |
| `PERMIT_DATE` | *(none in DATA)* |
| `FINAL_DATE` | *(none in DATA)* |

## Field assessment

### STATUS_NORMALIZED

**Before:** Active 1,148 · In Review 361 · Final 221 · Inactive 36 · missing 0

Upstream mapped `STATUS_ORIGINAL` (`active` / `draft` / `complete` / `stopped`) rather than the live numeric code. On 36 rows those strings lag `main.status`:

| `main.status` | Expected | Observed `STATUS_NORMALIZED` | n |
| --- | --- | --- | ---: |
| 2 (complete) | Final | Active | 34 |
| 2 (complete) | Final | In Review | 1 |
| −1 (stopped) | Inactive | Active | 1 |

When aligned, the code map is clean:

| `main.status` | `STATUS_ORIGINAL` | `STATUS_NORMALIZED` |
| --- | --- | --- |
| 0 | draft | In Review |
| 1 | active | Active |
| 2 | complete | Final |
| −1 | stopped | Inactive |

**After:** Active 1,113 · In Review 360 · Final 256 · Inactive 37 · missing 0  
Flags: **FILLED 0 · FIXED 36**

### FILE_DATE

**Before:** 0 missing (100%). Upstream used the UTC calendar day of `main.dateCreated`.

- Prefer `main.dateSubmitted` when present (true application/submittal date).
- Fall back to `dateCreated` for unsubmitted drafts (`status == 0`; all 360 In Review rows lack `dateSubmitted`).
- 53 rows had `FILE_DATE == dateCreated` while `dateSubmitted` fell 1–307 days later (median 3) → FIXED.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 53**

### PERMIT_DATE

**Before / after:** 1,766 missing (100%). Among Active/Final after status repair: 0 / 1,369.

Should be populated for Active and Final. DATA has no issuance/approval field. Nearby timestamps are not usable proxies:

- `expirationDate` ≈ an internal event + ~365 days (validity window; present on only ~half of Active rows)
- `lastUpdatedDate` reflects later edits, not approval

Left missing rather than inventing values.  
Flags: **FILLED 0 · FIXED 0**

### FINAL_DATE

**Before / after:** 1,766 missing (100%). Among Final after status repair: 0 / 256.

Should be populated for Final. No completion / signoff / closed date in `main` or `extra`. `lastUpdatedDate` on Final rows is often same-day as submit or a later admin touch, so it is not a safe finaling proxy.

Left missing.  
Flags: **FILLED 0 · FIXED 0**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 0 | 36 | 0 → 0 |
| `FILE_DATE` | 0 | 53 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 1,766 → 1,766 |
| `FINAL_DATE` | 0 | 0 | 1,766 → 1,766 |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_arvin.py`
- Repaired sample: `AGENT_DATA_PATH/arvin_repaired_sample.parquet`
