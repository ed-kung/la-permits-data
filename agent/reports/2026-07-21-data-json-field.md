# DATA JSON field vs FILE/PERMIT/FINAL dates and STATUS

**Summary:** `DATA` is a always-populated JSON string of the jurisdiction’s raw permit payload. Top-level `FILE_DATE`, `PERMIT_DATE`, `FINAL_DATE`, and `STATUS_ORIGINAL` are extracted from it (schema varies by source system). `STATUS_NORMALIZED` is a Dewey crosswalk of the original status into a small vocabulary (`Final`, `Active`, `Inactive`, `In Review`, …)—it usually does **not** appear verbatim in `DATA`. Match rates for dates are high for Accela-like portals on apply/issue dates; weaker for permit/final on task-event schemas. Notable pitfalls: Claremont/Azusa/Beverly Hills often map `FINAL_DATE` from an **expiration** field; Long Beach’s JSON key `Final Date` is a status string, while the column comes from `Status Date`.

## Method

- File: `MY_DATA_PATH/processed_data/dewey_ca_la_county_permits.parquet`
- Reservoir sample of **300 rows per jurisdiction** (35 jurisdictions), parse `DATA` as JSON
- Walk nested values; find keys whose parsed date/string equals each top-level column
- Script: `agent/scripts/explore_data_json_field.py`
- Artifacts: `AGENT_DATA_PATH/data_json_explore/`

`DATA` null rate was **0%** in the full scan for all jurisdictions.

## What `DATA` is

Jurisdiction-native scrape/API payloads, not a uniform Dewey schema. About **11 schema families** by top-level key fingerprint:

| Family | Example jurisdictions | Typical top-level keys |
| --- | --- | --- |
| Accela-like | LA County, Pasadena, Glendale, Arcadia, … | `entity`, `details`, `fees`, `contacts`, `processing_status` |
| Citizen Access / tasks | Santa Clarita, Torrance, Santa Monica, Downey, … | `date`, `status`, `tasks`, `search_data`, `inspections` |
| permit_info portal | Gardena, El Segundo, Glendora | `permit_info`, `site_info`, `inspections`, `fees` |
| My Project | Calabasas, Palos Verdes Estates | `My Project`, `Build Status`, `Permit Details` |
| Data Details | Claremont, Azusa | `Data Details`, `System Status`, `Type` |
| LADBS | Los Angeles | `Permit Application Status History`, `Current Status`, `Permit Issued` |
| Custom one-offs | Burbank, Long Beach, Beverly Hills, Compton, Lomita | each unique |

Culver City mixes two schemas (Citizen Access–like and a flatter `DateOpened` / `RecordStatus` layout).

## How dates connect

Canonical extraction pattern (names vary by family):

| Top-level column | Typical `DATA` source | Notes |
| --- | --- | --- |
| `FILE_DATE` | Apply / Applied / App. Date / DateOpened / `date` / Submitted / `dateCreated` | Most reliable; often ~100% match when the column is non-null |
| `PERMIT_DATE` | Issue / Issued / PermitIssuedDate | Strong on Accela / permit_info; weaker where issue date only lives in `tasks[].events` |
| `FINAL_DATE` | Final / Finalize / Finaled / Completed / Closed | Often missing in source JSON; sometimes **mis-sourced** (see pitfalls) |

### Accela-like (clearest mapping)

Example Pasadena / LA County:

- `FILE_DATE` ← `entity.ApplyDate` (also `details.ApplyDate`) — ~100%
- `PERMIT_DATE` ← `entity.IssueDate` / `details.IssueDate` — ~75–96% when column present
- `FINAL_DATE` ← `entity.FinalDate` / `details.FinalizeDate` — ~50–85%
- `STATUS_ORIGINAL` ← `entity.CaseStatus` (≈ `details.PermitStatus`) — ~98–100%

### City of Los Angeles

Dates are not clean scalar fields. They are embedded in:

- free text: `Permit Issued` = `"Issued on 2/21/2003"`, `Current Status` = `"Permit Finaled … on 9/28/2004"`
- arrays: `Permit Application Status History` = `[["Issued","2/21/2003",…], ["Permit Finaled","9/27/2004",…]]`

So `PERMIT_DATE` / `FINAL_DATE` match history entry dates (~82% / ~56% in sample); `FILE_DATE` is often null and only weakly recoverable from history.

### Long Beach

Misleading key names:

- JSON `Final Date` is usually a **status label** (e.g. `"Closed"`), not a date — and often equals `Project Status`
- Column `FINAL_DATE` comes from **`Status Date`** when present (~53% of sample rows have that key)
- No usable FILE/PERMIT dates in `DATA`

### Compton / Lomita

- Compton: sparse keys (`Issue Date`, `Status`, `Permit Type`, …) — explains PERMIT-only coverage
- Lomita: `main.dateCreated` → `FILE_DATE` (100%); status is numeric `main.status`, not the text in `STATUS_*`

## How status connects

1. **`STATUS_ORIGINAL`** ≈ raw status string from `DATA` (casefolded), e.g. `entity.CaseStatus`, `status`, `Permit Status`, `Build Status`, `Project Status`. Match rates typically **97–100%**.
2. **`STATUS_NORMALIZED`** = Dewey mapping of that original into a short vocabulary. Rarely equals any `DATA` string. Examples from samples:

| STATUS_ORIGINAL | STATUS_NORMALIZED |
| --- | --- |
| finaled / final / permit finaled / closed / complete | Final |
| issued / permit issued | Active |
| expired / void / canceled / withdrawn | Inactive |
| pending / applied / in review / draft | In Review |

So for analysis prefer `STATUS_NORMALIZED` for cross-jurisdiction work, and `STATUS_ORIGINAL` (or the `DATA` status key) when you need source wording.

## Pitfalls

1. **Expiration used as FINAL_DATE** — Claremont & Azusa: column often matches `Data Details.Expire Date`, not `Final Date` (and can disagree with a populated Final Date). Beverly Hills: high match to `activity.PERMIT EXPIRATION DATE`.
2. **Long Beach `Final Date` key ≠ date**.
3. **Citizen Access `tasks[].events`**: permit/final dates may only appear as workflow event timestamps; best-key match rates look noisy even when FILE_DATE is perfect.
4. **Claremont `System Status`** sometimes duplicated (`"Final Final"`, `"Expired Expired"`), so string equality to `STATUS_ORIGINAL` fails even though semantics match.

## Artifacts

- `AGENT_DATA_PATH/data_json_explore/field_mapping_by_jurisdiction.csv` — best matching key + rate per jurisdiction
- `…/jurisdiction_summary.json` — full key inventories and hit counters
- `…/samples_by_jurisdiction.json` — 4 truncated examples per jurisdiction
