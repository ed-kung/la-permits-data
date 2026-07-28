# Avenal (CA) data repair

**Summary:** Avenal was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the OpenGov / SmartGov `DATA` JSON. Status was remapped from live numeric `main.status` (**FIXED 49**): stale `STATUS_ORIGINAL` labels had left 32 `complete` (status=2) rows as Active, 11 `active` (status=1) rows as Final, plus 6 other lag cases. `FILE_DATE` was corrected from `dateCreated` to `dateSubmitted` where the submittal fell on a later calendar day (**FIXED 209**); coverage remains 100%. `PERMIT_DATE` and `FINAL_DATE` are universally missing and cannot be recovered — the payload has no issuance or finaling timestamps.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Avenal, CA** (n=2,000) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/ca/data_repair_ca_avenal.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_avenal_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `main`, `extra`, and `location`. Sub-schemas reflect `extra` form content and record type:

| Schema | n | Description |
| --- | ---: | --- |
| `business_license_form` | 1,040 | Business license fields (Type of Business, Start Date of Business in Avenal, …) |
| `building_numeric` | 484 | Building / trade permits with numeric OpenGov field IDs |
| `other_form` | 183 | Misc. named forms (vendors, parking, fireworks, …) |
| `encroachment_form` | 147 | Encroachment fields (Type of Encroachment, Acceptance of Conditions, …) |
| `planning_form` | 37 | Uniform Application / variance / lot-line fields |
| `building_form` | 37 | Named building fields (Type of Construction, …) |
| `solar_form` | 35 | SolarAPP+ permit fields |
| `temporary_event_form` | 15 | Temporary use / special-event applications |
| `code_enforcement_form` | 15 | Code-enforcement complaint / violation fields |
| `numeric_legacy` | 4 | Other numeric OpenGov IDs |
| `empty_extra` | 3 | Empty `extra` dict |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `main.status` (−1/0/1/2) |
| `FILE_DATE` | `main.dateSubmitted` (fallback: `dateCreated`) |
| `PERMIT_DATE` | *(none in DATA)* |
| `FINAL_DATE` | *(none in DATA)* |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 835 · Active 590 · In Review 533 · Inactive 42 · missing 0

Upstream mapped `STATUS_ORIGINAL` (`active` / `draft` / `complete` / `stopped`) rather than the live numeric code. On 49 rows those strings lag `main.status`:

| `main.status` | Expected | Observed `STATUS_NORMALIZED` | n |
| --- | --- | --- | ---: |
| 2 (complete) | Final | Active | 32 |
| 1 (active) | Active | Final | 11 |
| 0 (draft) | In Review | Active | 2 |
| −1 (stopped) | Inactive | Active | 2 |
| 0 (draft) | In Review | Final | 1 |
| 2 (complete) | Final | Inactive | 1 |

When aligned, the code map is clean:

| `main.status` | `STATUS_ORIGINAL` | `STATUS_NORMALIZED` |
| --- | --- | --- |
| 0 | draft | In Review |
| 1 | active | Active |
| 2 | complete | Final |
| −1 | stopped | Inactive |

**After:** Final 856 · Active 565 · In Review 536 · Inactive 43 · missing 0  
Flags: **FILLED 0 · FIXED 49**

### FILE_DATE

**Before:** 0 missing (100%). Upstream used the UTC calendar day of `main.dateCreated` for all 2,000 rows.

- Prefer `main.dateSubmitted` when present (true application/submittal date).
- Fall back to `dateCreated` for unsubmitted drafts (`status == 0`; 536 rows lack `dateSubmitted`).
- 209 rows had `FILE_DATE == dateCreated` while `dateSubmitted` fell 1–461 days later (median 3) → FIXED.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 209**

Coverage after: **100%**.

### PERMIT_DATE

**Before / after:** 2,000 missing (100%). Among Active/Final after status repair: 0 / 1,421.

Should be populated for Active and Final. DATA has no issuance/approval field. Nearby timestamps and form dates are not usable proxies:

- `expirationDate` / extra `Expires` / `Expiration Date` are validity windows, not issuance
- `Clerk Date` / `Planning Dept Date` keys exist on business licenses but are always empty
- Extra `Date` / acceptance-of-conditions dates are applicant form stamps, not approvals
- `lastUpdatedDate` reflects later edits, not approval

Left missing rather than inventing values.  
Flags: **FILLED 0 · FIXED 0**

### FINAL_DATE

**Before / after:** 2,000 missing (100%). Among Final after status repair: 0 / 856.

Should be populated for Final. No completion / signoff / closed date in `main` or `extra`. On Final rows, `lastUpdatedDate` equals `dateSubmitted` on ~489 rows and is later on ~367 (median gap 7 days) — often an admin touch, not a reliable finaling proxy.

Left missing.  
Flags: **FILLED 0 · FIXED 0**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 0 | 49 | 0 → 0 |
| `FILE_DATE` | 0 | 209 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 2,000 → 2,000 |
| `FINAL_DATE` | 0 | 0 | 2,000 → 2,000 |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_avenal.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_ca_avenal_repaired.parquet`
