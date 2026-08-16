# Harris County (TX) data repair — STATUS_NORMALIZED and dates

**Summary:** Among TX sample jurisdictions in first-appearance order, Harris County is the first without an existing repair script. DATA is ~66% permit-level payloads (`permit_status` / nested `event_logs`) and ~34% application-level payloads (`project_details.status:` / top-level `event_logs`). Main defects: 525 null statuses despite usable agency status, FILE_DATE often missing or taken from Issued/In Progress instead of Submit, PERMIT_DATE frequently missing or set to `permit_effective_start_date` (often Issued+180 validity, not issuance), and 1,403 spurious FINAL_DATE values on non-Final rows (no Final/completion signal exists). After repair, every row has STATUS and FILE_DATE, Active rows have 100% PERMIT_DATE coverage, and FINAL_DATE is empty for all rows.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`. Walking unique `(JURISDICTION, STATE)` in first-appearance order, existing TX scripts cover Austin, Fort Worth, Houston, San Antonio, and Dallas. **Harris County** is the first gap → `agent/scripts/tx/data_repair_tx_harris_county.py`.

Sample size: **2,002** Harris County records.

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Distinguishing keys / shape |
| --- | ---: | --- |
| `permit` | 1,327 | `permit_status`, `permit_effective_*`, `details`, `project_data` |
| `application` | 675 | `app_id`, `event_logs`, `project_details`, `permit_requests` |

Both families share the same event-log vocabulary (`Draft`, `Submit`, `Issued`, `Cancel`, …). Application status comes from `project_details.status:`; permit status from top-level `permit_status`.

## Field assessment (before repair)

### STATUS_NORMALIZED

| Value | n |
| --- | ---: |
| Active | 1,331 |
| (null) | 525 |
| In Review | 83 |
| Inactive | 63 |
| Final | 0 |

**Incorrectly missing (fillable, 525):** Agency status present for every null row — e.g. `Issued`→Active (400), `Return to Customer`→In Review (43), `Cancel`→Inactive (33), `Final Approval`→In Review (29), plus smaller In Progress / Assigned / Refund / revision variants.

**Incorrect non-null (12):** `Revision: In-Revision` stored as Active (8) or Inactive (1) → In Review; `Issued` stored as Inactive (2) → Active; `Ready for Payment` stored as Active (1) → In Review.

Upstream `STATUS_ORIGINAL` only encodes a coarse subset (`issued` / `in progress` / `cancel` / …), so many application workflow states never mapped into `STATUS_NORMALIZED`.

### FILE_DATE

- Missing: **426 / 2,002** — all on `permit` schema; all fillable from `project_data.event_logs` Submit/Draft
- Present mismatches vs Submit/Draft: **406** — often equal to permit-level `In Progress` or `Issued` instead of application Submit
- Application schema usually already matches Submit/Draft (59 Draft-only day offsets vs Submit)

### PERMIT_DATE

- Missing: **1,377**
- Present (625): almost all equal `permit_effective_start_date`, **not** the `Issued` event
- `Issued` event vs `permit_effective_start_date` differs by **+180 days** in ~1,079 permit rows (and similarly on application `permit_requests`) — the start field behaves like a validity / mid-term offset, not issuance
- Therefore most present PERMIT_DATE values are incorrect; Issued-event date is the right issuance signal
- All Active/Issued gaps are fillable from an Issued event (or rare start fallback)

### FINAL_DATE

- Present on **1,403** rows — all non-Final (Active 1,301 / In Review 61 / Inactive 41)
- Values track Issued date, FILE_DATE, or expiration-like offsets — not completion
- No completion / CO / finaled events in DATA → nothing to populate for Final

## Repair behavior

Canonical mappings:

- Status ← `permit_status` or `project_details.status:` via fixed map (`Issued*`→Active, review/payment/return/revision workflow→In Review, `Cancel`/`Refund`→Inactive)
- `FILE_DATE` ← first `Submit` in application-level event logs, else `Draft`
- `PERMIT_DATE` ← first `Issued` event (details/project logs for `permit`; top-level logs for `application`); fallback to `permit_effective_start_date` only when no Issued event
- `FINAL_DATE` ← cleared whenever effective status is not Final

Flags: `FILLED` for former missings; `FIXED` for corrected or cleared values. `INFERRED_SCHEMA` set per row.

## Performance (after repair)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 525 | 12 | 525 → 0 |
| FILE_DATE | 426 | 406 | 426 → 0 |
| PERMIT_DATE | 1,120 | 576 | 1,377 → 257 |
| FINAL_DATE | 0 | 1,403 | 599 → 2,002 (cleared) |

Status after: Active 1,724 / In Review 183 / Inactive 95 / Final 0.

| Status (after) | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 1,724 / 1,724 (100%) | 0 / 1,724 |
| In Review | 11 / 183 (6.0%) | 0 / 183 |
| Inactive | 10 / 95 (10.5%) | 0 / 95 |

Remaining missing `PERMIT_DATE` (257) are non-issued In Review / Inactive rows with no Issued event. The small In Review / Inactive shares with PERMIT_DATE retain a historical Issued event (e.g. later Cancel or revision).

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_harris_county.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_harris_county_repaired.parquet`
