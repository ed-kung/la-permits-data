# Seagoville (TX) data repair

**Summary:** Seagoville was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. Its DATA column is a CitizenServe portal payload (`main` / `extra` / `location`), same family as Bedford. Of 2,000 sample rows, the repair FIXES 2 STATUS_NORMALIZED mismatches against `main.status` and 87 FILE_DATEs that lagged `dateSubmitted`. PERMIT_DATE and FINAL_DATE remain universally missing — DATA has no reliable issuance or finaling timestamps.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in sample order. Existing TX scripts covered through Portland; **Seagoville, TX** was the first missing (`agent/scripts/tx/data_repair_tx_seagoville.py`).

## DATA schema

Every record has top-level keys `main`, `extra`, `location` (`location` is null on 656 rows). `main.status` codes map to portal lifecycle (`0=draft`, `1=active`, `2=complete`, `-1=stopped`). Content variants recorded in `INFERRED_SCHEMA`:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| citizenserve_building | 1,073 | Building, CO, electrical, plumbing, mechanical, fire, sign |
| citizenserve_draft | 470 | `main.status == 0` |
| citizenserve_registration | 333 | Contractor registration, short-term rental |
| citizenserve_other | 120 | Flea market, health, itinerant vendor, etc. |
| citizenserve_planning | 4 | Development/zoning, board of adjustments (non-draft) |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `main.status` | — |
| FILE_DATE | `main.dateSubmitted` | `main.dateCreated` |
| PERMIT_DATE | — (none reliable) | — |
| FINAL_DATE | — (none reliable) | — |

## Findings by field

### STATUS_NORMALIZED

Before: Active 866, Final 639, In Review 471, Inactive 24. No missing values.

`main.status` × STATUS_NORMALIZED is nearly 1:1, with **2 mismatches**:

1. **E-24-93** (Electrical Permit): `status=1` but labeled In Review / `STATUS_ORIGINAL=draft` → **Active** (FIXED).
2. **FD-23-60** (Fire Department): `status=2` but labeled Active / `STATUS_ORIGINAL=active` → **Final** (FIXED).

After: Active 866, Final 640, In Review 470, Inactive 24. **FILLED 0, FIXED 2.**

~27 rows carry `deletionReason` with `isEnabled=False` (duplicates, cancellations, archives) while `main.status` remains 1 or 2. Repair keeps `main.status` authoritative so STATUS stays aligned with the portal lifecycle code (same convention as Bedford).

### FILE_DATE

Fully populated before repair (0 missing). Every row matched `main.dateCreated` at calendar-day resolution. Preferred source is `dateSubmitted` when present, else `dateCreated`:

- 1,443 rows already matched `dateSubmitted` (same UTC day as created).
- **87 rows** had `dateSubmitted` on a later calendar day (drafted then submitted later; median gap 4 days) — FILE_DATE FIXED to the submittal date.
- 470 drafts lack `dateSubmitted`; FILE_DATE correctly remains `dateCreated`.

Applicant-entered extra dates (`Date/Fecha`, `Date of Application`) usually echo created or submitted and are not used as a separate source.

Ideal: populated for all records — **achieved (100%)**.

### PERMIT_DATE

Universally missing (2,000 / 2,000) before and after. DATA has no issuance or approval timestamp. `extra` inspection checkboxes (`HVAC Final`, `Plumbing Final`, `Electrical Final`) are empty strings. Numeric ASI-looking keys next to contractor fields and `expirationDate` / `lastUpdatedDate` are not safe issuance proxies (expiration often present on Active and Final; `lastUpdatedDate` equals created day for ~54% of Final rows).

Ideal: populated for Active and Final — **not achievable from DATA** (0/866 Active, 0/640 Final).

### FINAL_DATE

Universally missing (2,000 / 2,000). No finaled / completion / signoff field in `main` or `extra`. `Approval/Denial` / `Approved/Denied` on planning forms are nearly always blank.

Ideal: populated for Final — **not achievable from DATA** (0/640).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 2 | 0 → 0 |
| FILE_DATE | 0 | 87 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Post-repair coverage:

- Active: FILE 100%, PERMIT 0%, FINAL 0%
- Final: FILE 100%, PERMIT 0%, FINAL 0%
- In Review: FILE 100%, PERMIT 0%, FINAL 0% (correct for permit/final)
- Inactive: FILE 100%, PERMIT 0%, FINAL 0%

## Not repairable

- All Active/Final rows lack issuance timestamps in DATA → PERMIT_DATE stays missing.
- All Final rows lack finaling/completion timestamps in DATA → FINAL_DATE stays missing.
- Archived / duplicate shells with `deletionReason` left at portal `main.status` (not remapped to Inactive).

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_seagoville.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_tx_seagoville_repaired.parquet`
