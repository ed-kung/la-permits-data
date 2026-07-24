# Lomita CA data repair

**Summary:** Lomita’s 2,000 sample records use a single `main` / `extra` / `location` DATA schema. `STATUS_NORMALIZED` is fully populated and correctly mapped from numeric `main.status`. `FILE_DATE` was taken from `main.dateCreated`; 333 records should use `main.dateSubmitted` instead (later calendar day), and 1 missing `FILE_DATE` is fillable from `dateSubmitted`. `PERMIT_DATE` and `FINAL_DATE` are universally missing and cannot be recovered — the payload has no issuance or finaling timestamps. Repair script: `agent/scripts/data_repair_ca_lomita.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Lomita"`, `STATE == "CA"` |
| N | 2,000 |
| INFERRED_SCHEMA | `main_extra_location` (2,000 / 2,000) |

`STATUS_ORIGINAL` tracks `main.status` 1:1: `draft`(0), `active`(1), `complete`(2), `stopped`(-1).

## Field assessment

### STATUS_NORMALIZED — correct (0 FILLED / 0 FIXED)

| `main.status` | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | --- |
| 2 | complete | Final | 1,528 |
| 1 | active | Active | 254 |
| 0 | draft | In Review | 90 |
| -1 | stopped | Inactive | 128 |

No missing values; no disagreements with DATA. The repair function re-derives status for robustness but makes no changes on this sample.

### FILE_DATE — mostly correct; prefer submittal over create

- Ideal: application / submittal date for all records.
- Upstream set `FILE_DATE` to the UTC calendar date of `main.dateCreated` (1,999 / 1,999 non-null matches).
- Prefer `main.dateSubmitted` when present (true submittal); fall back to `dateCreated` for unsubmitted drafts (`status == 0`, all 90 In Review rows lack `dateSubmitted`).

| Issue | n | Action |
| --- | --- | --- |
| `FILE_DATE` calendar day ≠ `dateSubmitted` | 333 | FIXED → `dateSubmitted` |
| `FILE_DATE` null, `dateSubmitted` present | 1 | FILLED → `dateSubmitted` |
| After repair missing | 0 | — |

### PERMIT_DATE — unfillable (0 / 2,000)

Should be populated for Active and Final. DATA has no issuance/approval field. Nearby timestamps are not usable proxies:

- `expirationDate` ≈ create/submit + 365 days (validity window, not issuance)
- `lastUpdatedDate` reflects later edits / renewals, not approval

Left missing rather than inventing values from file or expiration dates.

### FINAL_DATE — unfillable (0 / 2,000)

Should be populated for Final. No completion / signoff / closed date in `main` or `extra`. `lastUpdatedDate` on Final rows is often same-day as submit or years later (e.g. business-license renewals), so it is not a safe finaling proxy.

## Repair function

`agent/scripts/data_repair_ca_lomita.py` → `data_repair(df)`

- Overwrites incorrect / missing fields from DATA
- Adds `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`} and `INFERRED_SCHEMA`
- CLI preview on the LA sample: STATUS unchanged; FILE_DATE 1 FILLED + 333 FIXED; PERMIT/FINAL unchanged (still fully missing)

## Artifacts

- `agent/scripts/data_repair_ca_lomita.py`
